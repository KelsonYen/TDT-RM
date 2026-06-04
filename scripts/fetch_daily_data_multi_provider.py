#!/usr/bin/env python
"""Fetch strict daily TDT-RM input CSVs through a multi-provider fallback layer.

The script only owns provider acquisition, normalization, CSV generation, and a
machine-readable fetch summary. It does not change scoring models or signal
rules, and it fails closed when every configured provider for a dataset fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tdt_rm.data_providers import (  # noqa: E402
    CSV_BY_DATASET,
    DATASETS,
    DatasetFetchResult,
    FinMindProvider,
    ProviderContext,
    ProviderError,
    PublicFXProvider,
    StooqProvider,
    TAIFEXProvider,
    TWSEProvider,
    YahooProvider,
)
from tdt_rm.data_providers.normalizers import write_strict_csv  # noqa: E402
from tdt_rm.public_data_fetchers import load_main7_symbols  # noqa: E402
from validate_daily_input_csvs import validate_daily_input_csvs  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch daily TDT-RM CSVs with TWSE/TAIFEX/FX/Yahoo/Stooq/FinMind fallback chains.")
    parser.add_argument("--trade-date", required=True, type=date.fromisoformat, help="Target trade date YYYY-MM-DD.")
    parser.add_argument("--input-dir", required=True, help="Output directory for the seven strict daily CSVs.")
    parser.add_argument("--summary-json", help="Path for multi-provider fetch summary JSON.")
    parser.add_argument("--source-config", help="Optional public data source config JSON/YAML.")
    parser.add_argument("--main7-config", default="config/main7_symbols.json", help="JSON file containing Main-7 symbols.")
    parser.add_argument("--lookback-days", type=int, default=180, help="Historical lookback for derived indicators (default: 180).")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds (default: 30).")
    parser.add_argument("--sleep-seconds", type=float, default=0.25, help="FinMind polite delay seconds (default: 0.25).")
    parser.add_argument("--validate", action="store_true", help="Run strict daily input CSV validation after fetch.")
    args = parser.parse_args(_normalize_dash_args(sys.argv[1:]))

    fetched_at = datetime.now(UTC).replace(microsecond=0)
    input_dir = Path(args.input_dir)
    input_dir.mkdir(parents=True, exist_ok=True)
    summary_path = Path(args.summary_json) if args.summary_json else Path("outputs") / f"multi_provider_fetch_summary_{args.trade_date.isoformat()}.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    main7 = load_main7_symbols(args.main7_config)
    context = ProviderContext(
        trade_date=args.trade_date,
        fetched_at=fetched_at,
        lookback_days=args.lookback_days,
        timeout=args.timeout,
        sleep_seconds=args.sleep_seconds,
        main7_symbols=main7,
        main7_config=args.main7_config,
    )

    chains = _provider_chains(args.source_config)
    results: dict[str, DatasetFetchResult] = {}
    for dataset in DATASETS:
        results[dataset] = _fetch_dataset(dataset, chains[dataset], context, input_dir)

    if args.validate and all(result.ok for result in results.values()):
        validation_errors = validate_daily_input_csvs(trade_date=args.trade_date, input_dir=input_dir)
        if validation_errors:
            results["validation"] = DatasetFetchResult("validation", "failed", failed_providers=(ProviderError("validate_daily_input_csvs", "; ".join(validation_errors)),))

    missing = [f"{dataset}.csv" for dataset, result in results.items() if dataset in DATASETS and not result.ok]
    summary = {
        "trade_date": args.trade_date.isoformat(),
        "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
        "input_dir": str(input_dir),
        "datasets": {dataset: result.as_dict() for dataset, result in results.items() if dataset in DATASETS},
        "missing_datasets": missing,
        "overall_status": "READY" if not missing else "NOT_READY",
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    _print_summary(summary)
    return 0 if not missing else 1


def _normalize_dash_args(argv: list[str]) -> list[str]:
    """Accept copied commands that use Unicode en/em dashes before option names."""

    return [arg.replace("–", "--", 1).replace("—", "--", 1) if arg.startswith(("–", "—")) else arg for arg in argv]


def _provider_chains(source_config: str | None) -> dict[str, tuple[object, ...]]:
    twse = TWSEProvider(source_config)
    taifex = TAIFEXProvider(source_config)
    public_fx = PublicFXProvider(source_config)
    yahoo = YahooProvider()
    stooq = StooqProvider()
    finmind = FinMindProvider()
    return {
        "price": (twse, yahoo, stooq, finmind),
        "foreign_flow": (twse, finmind),
        "fx": (public_fx, taifex, yahoo, finmind),
        "breadth": (twse, finmind),
        "futures": (taifex, finmind),
        "options": (taifex, finmind),
        "leadership": (twse, yahoo, finmind),
    }


def _fetch_dataset(dataset: str, providers: Iterable[object], context: ProviderContext, input_dir: Path) -> DatasetFetchResult:
    failures: list[ProviderError] = []
    path = input_dir / CSV_BY_DATASET[dataset]
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    for provider in providers:
        name = str(getattr(provider, "name", provider.__class__.__name__))
        try:
            result = provider.fetch(dataset, context)  # type: ignore[attr-defined]
            write_strict_csv(path, dataset, result.row)
            return DatasetFetchResult(dataset, "success", provider_used=result.provider, output_path=str(path), failed_providers=tuple(failures))
        except Exception as exc:  # noqa: BLE001 - failure should advance to next provider.
            failures.append(ProviderError(name, str(exc)))
    return DatasetFetchResult(dataset, "failed", failed_providers=tuple(failures))


def _print_summary(summary: dict[str, object]) -> None:
    print("MULTI-PROVIDER DATA FETCH RESULT")
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
    print(f"overall_status: {summary.get('overall_status')}")
    missing = summary.get("missing_datasets")
    if missing:
        print("missing_datasets: " + ", ".join(str(item) for item in missing))


if __name__ == "__main__":
    raise SystemExit(main())
