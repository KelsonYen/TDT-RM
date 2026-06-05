#!/usr/bin/env python
"""Fetch strict daily TDT-RM input CSVs through a hardened provider pipeline.

The script only owns provider acquisition, normalization, schema validation,
provider health, reconciliation checks, CSV generation, and a machine-readable
fetch summary. It does not change scoring models or signal rules. FinMind is a
last-resort fallback and is disabled unless explicitly opted in.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tdt_rm.data_providers import (  # noqa: E402
    CBCProvider,
    CSV_BY_DATASET,
    DATASETS,
    DatasetFetchResult,
    FinMindProvider,
    ProviderContext,
    ProviderError,
    ProviderHealth,
    StooqProvider,
    TAIFEXProvider,
    TWSEProvider,
    TaiwanIndexPlusProvider,
    YahooProvider,
)
from tdt_rm.data_providers.normalizers import reconciliation_checks, validate_strict_row, write_strict_csv  # noqa: E402
from tdt_rm.public_data_fetchers import load_main7_symbols  # noqa: E402
from validate_daily_input_csvs import validate_daily_input_csvs  # noqa: E402


_PROVIDER_PRIORITY = ("TWSE_OFFICIAL", "TAIFEX_OFFICIAL", "CBC_OFFICIAL", "TAIWAN_INDEX_PLUS_OFFICIAL", "YAHOO_FINANCE", "STOOQ", "FINMIND_FALLBACK")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch daily TDT-RM CSVs with official-source-first fallback chains.")
    parser.add_argument("--trade-date", required=True, type=date.fromisoformat, help="Target trade date YYYY-MM-DD.")
    parser.add_argument("--input-dir", required=True, help="Output directory for the eight strict daily CSVs.")
    parser.add_argument("--summary-json", help="Path for multi-provider fetch summary JSON.")
    parser.add_argument("--provider-health-json", help="Optional path for provider_health.json diagnostics.")
    parser.add_argument("--source-config", help="Optional public data source config JSON/YAML.")
    parser.add_argument("--main7-config", default="config/main7_symbols.json", help="JSON file containing Main-7 symbols.")
    parser.add_argument("--lookback-days", type=int, default=180, help="Historical lookback for derived indicators (default: 180).")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds (default: 30).")
    parser.add_argument("--sleep-seconds", type=float, default=0.25, help="FinMind polite delay seconds (default: 0.25).")
    parser.add_argument("--allow-finmind-live", action="store_true", help="Opt in to live FinMind fallback. Disabled by default so production does not depend on FinMind reachability.")
    parser.add_argument("--validate", action="store_true", help="Run strict daily input CSV validation after fetch.")
    args = parser.parse_args(_normalize_dash_args(sys.argv[1:]))

    fetched_at = datetime.now(UTC).replace(microsecond=0)
    input_dir = Path(args.input_dir)
    input_dir.mkdir(parents=True, exist_ok=True)
    summary_path = Path(args.summary_json) if args.summary_json else Path("outputs") / f"multi_provider_fetch_summary_{args.trade_date.isoformat()}.json"
    health_path = Path(args.provider_health_json) if args.provider_health_json else input_dir / "provider_health.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    health_path.parent.mkdir(parents=True, exist_ok=True)

    allow_finmind_live = _allow_finmind_live(args)

    main7 = load_main7_symbols(args.main7_config)
    context = ProviderContext(
        trade_date=args.trade_date,
        fetched_at=fetched_at,
        lookback_days=args.lookback_days,
        timeout=args.timeout,
        sleep_seconds=args.sleep_seconds,
        main7_symbols=main7,
        main7_config=args.main7_config,
        allow_finmind_live=allow_finmind_live,
    )

    chains = _provider_chains(args.source_config)
    results: dict[str, DatasetFetchResult] = {}
    for dataset in DATASETS:
        results[dataset] = _fetch_dataset(dataset, chains[dataset], context, input_dir)

    validation_errors: list[str] = []
    if args.validate:
        validation_errors = validate_daily_input_csvs(trade_date=args.trade_date, input_dir=input_dir)
        if validation_errors:
            results["validation"] = DatasetFetchResult("validation", "failed", failed_providers=(ProviderError("validate_daily_input_csvs", "; ".join(validation_errors)),), validation_errors=tuple(validation_errors))

    missing = [f"{dataset}.csv" for dataset, result in results.items() if dataset in DATASETS and not result.ok]
    provider_health = _provider_health_payload(results, args.trade_date, fetched_at, validation_errors)
    health_path.write_text(json.dumps(provider_health, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    finmind_status = _finmind_fallback_status(allow_finmind_live)
    summary = {
        "trade_date": args.trade_date.isoformat(),
        "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
        "input_dir": str(input_dir),
        "provider_priority": list(_PROVIDER_PRIORITY),
        "finmind_live_enabled": allow_finmind_live,
        "finmind_fallback": finmind_status,
        "datasets": {dataset: result.as_dict() for dataset, result in results.items() if dataset in DATASETS},
        "missing_datasets": missing,
        "validation_errors": validation_errors,
        "provider_health_path": str(health_path),
        "provider_health_summary": provider_health["summary"],
        "overall_status": "READY" if not missing and not validation_errors and not provider_health["summary"]["failed_providers"] else "NOT_READY",
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    _print_summary(summary)
    return 0 if summary["overall_status"] == "READY" else 1


def _allow_finmind_live(args: argparse.Namespace) -> bool:
    return bool(
        args.allow_finmind_live
        or os.getenv("TDT_RM_ALLOW_FINMIND_LIVE", "").strip().lower() in {"1", "true", "yes", "y", "on"}
    )


def _normalize_dash_args(argv: list[str]) -> list[str]:
    """Accept copied commands that use Unicode en/em dashes before option names."""

    return [arg.replace("–", "--", 1).replace("—", "--", 1) if arg.startswith(("–", "—")) else arg for arg in argv]


def _finmind_fallback_status(allow_finmind_live: bool) -> dict[str, Any]:
    token_present = bool(os.environ.get("FINMIND_TOKEN"))
    api_token_present = bool(os.environ.get("FINMIND_API_TOKEN"))
    env_opt_in = os.environ.get("TDT_RM_ALLOW_FINMIND_LIVE", "").strip().lower() in {"1", "true", "yes", "y", "on"}
    allowed = bool(allow_finmind_live or env_opt_in)
    has_token = bool(token_present or api_token_present)
    return {
        "allow_finmind": allowed,
        "finmind_token_present": token_present,
        "finmind_api_token_present": api_token_present,
        "token_present": has_token,
        "skipped": not (allowed and has_token),
        "skip_reason": "" if allowed and has_token else (
            "missing FINMIND_TOKEN/FINMIND_API_TOKEN" if allowed else "allow_finmind false"
        ),
    }


def _provider_chains(source_config: str | None) -> dict[str, tuple[object, ...]]:
    twse = TWSEProvider(source_config)
    taifex = TAIFEXProvider(source_config)
    cbc = CBCProvider(source_config)
    tip = TaiwanIndexPlusProvider(source_config)
    yahoo = YahooProvider()
    stooq = StooqProvider()
    finmind = FinMindProvider()
    return {
        "price": (twse, tip, yahoo, stooq, finmind),
        "foreign_flow": (twse, finmind),
        "fx": (taifex, cbc, yahoo, finmind),
        "breadth": (twse, finmind),
        "futures": (taifex, finmind),
        "options": (taifex, finmind),
        "leadership": (twse, yahoo, finmind),
        "margin": (twse, finmind),
    }


def _fetch_dataset(dataset: str, providers: Iterable[object], context: ProviderContext, input_dir: Path) -> DatasetFetchResult:
    failures: list[ProviderError] = []
    health: list[ProviderHealth] = []
    path = input_dir / CSV_BY_DATASET[dataset]
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    for provider in providers:
        name = str(getattr(provider, "name", provider.__class__.__name__))
        try:
            result = provider.fetch(dataset, context)  # type: ignore[attr-defined]
            validation_errors = validate_strict_row(dataset, result.row)
            checks = reconciliation_checks(dataset, result.row)
            failed_checks = [check for check in checks if not check.ok]
            if validation_errors or failed_checks:
                message = "; ".join(validation_errors + [check.message or check.name for check in failed_checks])
                failures.append(ProviderError(name, f"strict validation/reconciliation failed: {message}"))
                health.append(ProviderHealth(name, dataset, "failed", failure_reason=message, checks=checks, metadata=result.raw_metadata))
                continue
            _write_raw_provider_file(input_dir, dataset, name, "success", {"row": dict(result.row), "raw_source": result.raw_source, "raw_metadata": dict(result.raw_metadata)})
            write_strict_csv(path, dataset, result.row)
            health.append(ProviderHealth(name, dataset, "healthy", selected=True, output_path=str(path), checks=checks, metadata=result.raw_metadata))
            return DatasetFetchResult(dataset, "success", provider_used=result.provider, output_path=str(path), failed_providers=tuple(failures), provider_health=tuple(health), reconciliation_checks=checks)
        except Exception as exc:  # noqa: BLE001 - fail closed for this provider, then advance to next provider.
            provider_metadata = getattr(exc, "metadata", {})
            diagnostics = dict(provider_metadata) if isinstance(provider_metadata, Mapping) else {}
            diagnostics.update({"error": str(exc), "exception_class": exc.__class__.__name__, "traceback": traceback.format_exc()})
            _write_raw_provider_file(input_dir, dataset, name, "failed", diagnostics)
            failures.append(ProviderError(name, str(exc)))
            health.append(ProviderHealth(name, dataset, "failed", failure_reason=str(exc), metadata=diagnostics))
    return DatasetFetchResult(dataset, "failed", failed_providers=tuple(failures), provider_health=tuple(health), validation_errors=(f"all providers failed for {dataset}",))



def _write_raw_provider_file(input_dir: Path, dataset: str, provider: str, status: str, payload: Mapping[str, Any]) -> None:
    safe_provider = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in provider)
    raw_dir = input_dir / "_raw" / dataset
    raw_dir.mkdir(parents=True, exist_ok=True)
    output = {"dataset": dataset, "provider": provider, "status": status, **dict(payload)}
    (raw_dir / f"{safe_provider}.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def _provider_health_payload(results: Mapping[str, DatasetFetchResult], trade_date: date, fetched_at: datetime, validation_errors: list[str]) -> dict[str, Any]:
    providers: dict[str, Any] = {}
    for dataset, result in results.items():
        if dataset not in DATASETS:
            continue
        selected = next((item for item in result.provider_health if item.selected), None)
        providers[f"{dataset}_provider"] = {
            "dataset": dataset,
            "status": "healthy" if result.ok else "failed",
            "provider_used": result.provider_used,
            "output_path": result.output_path,
            "attempts": [item.as_dict() for item in result.provider_health],
            "failed_providers": [error.as_dict() for error in result.failed_providers],
            "reconciliation_checks": [check.as_dict() for check in result.reconciliation_checks],
            "final_decision": "use_provider" if result.ok else "block_pipeline",
            "source_selected": selected.provider if selected else None,
        }
    summary = {
        "total_providers": len(providers),
        "healthy_providers": sorted(name for name, item in providers.items() if item["status"] == "healthy"),
        "failed_providers": sorted(name for name, item in providers.items() if item["status"] == "failed"),
        "validation_failed": bool(validation_errors),
        "fail_closed": bool(validation_errors or any(item["status"] == "failed" for item in providers.values())),
    }
    return {
        "as_of": trade_date.isoformat(),
        "generated_at": fetched_at.isoformat().replace("+00:00", "Z"),
        "providers": providers,
        "summary": summary,
        "validation_errors": validation_errors,
    }


def _print_summary(summary: Mapping[str, Any]) -> None:
    print("HARDENED MULTI-PROVIDER DATA FETCH RESULT")
    datasets = summary.get("datasets")
    if isinstance(datasets, dict):
        for dataset, result in datasets.items():
            if not isinstance(result, dict):
                continue
            status = result.get("status")
            provider = result.get("provider_used") or "-"
            print(f"{dataset}: {status} provider={provider}")
            for failed in result.get("failed_providers", []) if isinstance(result.get("failed_providers"), list) else []:
                if isinstance(failed, dict):
                    print(f"  failed {failed.get('provider')}: {failed.get('message')}")
    finmind = summary.get("finmind_fallback")
    if isinstance(finmind, dict):
        print(
            "finmind_fallback: "
            f"allow_finmind={finmind.get('allow_finmind')} "
            f"FINMIND_TOKEN_present={finmind.get('finmind_token_present')} "
            f"FINMIND_API_TOKEN_present={finmind.get('finmind_api_token_present')} "
            f"skipped={finmind.get('skipped')} "
            f"skip_reason={finmind.get('skip_reason') or '-'}"
        )
    print(f"overall_status: {summary.get('overall_status')}")
    missing = summary.get("missing_datasets")
    if missing:
        print("missing_datasets: " + ", ".join(str(item) for item in missing))


if __name__ == "__main__":
    raise SystemExit(main())
