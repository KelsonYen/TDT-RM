#!/usr/bin/env python
"""GitHub Actions production fetch orchestrator for TDT-RM.

This wrapper runs the live provider fetchers in a normal CI network, materializes
an auditable production input directory under inputs/daily/YYYY-MM-DD, and
validates that no required production CSV is missing/stale/synthetic. It keeps
fetch/normalization/validation diagnostics but skips operator-facing daily
reports unless explicitly requested.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from validate_daily_input_csvs import validate_daily_input_csvs  # noqa: E402

FORBIDDEN_SOURCE_TYPES = {"demo", "mock", "synthetic", "fixture", "test", "sample", "stale", "local_csv_fallback", "local_json_fallback"}
REQUIRED_DATASETS = ("price", "foreign_flow", "fx", "breadth", "futures", "options", "leadership", "margin")
REQUIRED_STAGED_CSVS = tuple(f"{dataset}.csv" for dataset in REQUIRED_DATASETS)

REQUIRED_PRODUCTION_FILES = (
    "taiex_price.csv",
    "twse_foreign_investor.csv",
    "twse_margin.csv",
    "twse_market_breadth.csv",
    "twse_turnover_or_volume.csv",
    "taifex_futures_options.csv",
    "fx_usdtwd.csv",
    "manifest.json",
)


@dataclass(frozen=True)
class CsvSpec:
    filename: str
    required_columns: tuple[str, ...]
    numeric_columns: tuple[str, ...] = ()
    bool_columns: tuple[str, ...] = ()


CSV_SPECS: dict[str, CsvSpec] = {
    "taiex_price.csv": CsvSpec("taiex_price.csv", ("trade_date", "provider_source", "source_type", "close", "ma5", "ma20", "ma60"), ("close", "ma5", "ma20", "ma60")),
    "twse_foreign_investor.csv": CsvSpec("twse_foreign_investor.csv", ("trade_date", "provider_source", "source_type", "foreign_spot_net_buy", "foreign_spot_net_sell", "foreign_spot_net_sell_consecutive_days"), ("foreign_spot_net_buy", "foreign_spot_net_sell", "foreign_spot_net_sell_consecutive_days")),
    "twse_margin.csv": CsvSpec("twse_margin.csv", ("trade_date", "provider_source", "source_type", "margin_balance_5d_flat_or_down", "hot_stock_margin_fast_increase", "margin_balance_5d_increases", "index_5d_return_pct", "margin_balance_5d_decline_pct", "margin_not_retreating"), ("index_5d_return_pct", "margin_balance_5d_decline_pct"), ("margin_balance_5d_flat_or_down", "hot_stock_margin_fast_increase", "margin_balance_5d_increases", "margin_not_retreating")),
    "twse_market_breadth.csv": CsvSpec("twse_market_breadth.csv", ("trade_date", "provider_source", "source_type", "advancing_issues", "declining_issues"), ("advancing_issues", "declining_issues")),
    "twse_turnover_or_volume.csv": CsvSpec("twse_turnover_or_volume.csv", ("trade_date", "provider_source", "source_type", "turnover_amount"), ("turnover_amount",)),
    "taifex_futures_options.csv": CsvSpec("taifex_futures_options.csv", ("trade_date", "provider_source", "source_type", "futures_hedging_increases", "futures_hedging_significant", "pcr_stable", "pcr_rises", "vix_stable", "vix_rises", "tail_risk"), ("tail_risk",), ("futures_hedging_increases", "futures_hedging_significant", "pcr_stable", "pcr_rises", "vix_stable", "vix_rises")),
    "fx_usdtwd.csv": CsvSpec("fx_usdtwd.csv", ("trade_date", "provider_source", "source_type", "usd_twd_3d_change_pct", "usd_twd_5d_change_pct"), ("usd_twd_3d_change_pct", "usd_twd_5d_change_pct")),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the GitHub Actions production data-fetch pipeline.")
    parser.add_argument("--trade-date", required=True, type=date.fromisoformat, help="Trade date YYYY-MM-DD.")
    parser.add_argument("--inputs-root", default="inputs/daily", help="Root for production input directories.")
    parser.add_argument("--reports-root", default="reports/daily", help="Root for dated production reports.")
    parser.add_argument("--outputs-root", default="outputs/daily", help="Root for dated GitHub Actions fetch manifests and summaries.")
    parser.add_argument("--source-config", default="config/public_data_sources.json", help="Public provider source configuration.")
    parser.add_argument("--allow-finmind-live", action="store_true", help="Allow FinMind only as an explicit token-gated vendor fallback.")
    parser.add_argument("--skip-fetch", action="store_true", help="Testing hook: do not call live providers; consume an existing staging directory.")
    parser.add_argument("--skip-daily-report", action="store_true", help="Do not generate operator-facing dated/latest daily reports from this fetch helper.")
    parser.add_argument("--staging-canonical", action="store_true", help="Explicitly allow the strict provider CSV staging directory to be the canonical source for operator reports.")
    parser.add_argument("--staging-dir", help="Strict provider CSV staging dir (default: inputs/daily/<date>/_strict_provider_csvs).")
    args = parser.parse_args()

    trade_date = args.trade_date
    production_dir = REPO_ROOT / args.inputs_root / trade_date.isoformat()
    staging_dir = Path(args.staging_dir) if args.staging_dir else production_dir / "_strict_provider_csvs"
    reports_dir = REPO_ROOT / args.reports_root / trade_date.isoformat()
    outputs_dir = REPO_ROOT / args.outputs_root / trade_date.isoformat()
    artifacts_dir = reports_dir / "artifacts"
    fetch_summary = artifacts_dir / "production_fetch_summary.json"
    provider_health = artifacts_dir / "provider_health.json"
    raw_dir = artifacts_dir / "raw"
    normalized_dir = artifacts_dir / "normalized"
    validation_report = artifacts_dir / "validation_report.json"
    run_summary = artifacts_dir / "run_summary.json"
    fetch_manifest = outputs_dir / "fetch_manifest.json"
    outputs_summary = outputs_dir / "summary.json"

    outputs_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir.mkdir(parents=True, exist_ok=True)

    try:
        allow_finmind_live = _production_finmind_live_allowed(args.allow_finmind_live)
        if not args.skip_fetch:
            _run_fetchers(trade_date, staging_dir, fetch_summary, provider_health, args.source_config, allow_finmind_live)
        _copy_if_exists(fetch_summary, raw_dir / fetch_summary.name)
        _copy_if_exists(provider_health, raw_dir / provider_health.name)

        legacy_errors = validate_daily_input_csvs(trade_date=trade_date, input_dir=staging_dir)
        _mirror_directory(staging_dir, normalized_dir)
        _write_validation_report(validation_report, trade_date, staging_errors=legacy_errors, production_errors=[])
        if legacy_errors:
            raise RuntimeError("strict provider CSV validation failed: " + "; ".join(legacy_errors))

        build_production_input_directory(trade_date=trade_date, staging_dir=staging_dir, production_dir=production_dir, fetch_summary_path=fetch_summary, provider_health_path=provider_health)
        production_errors = validate_required_production_files(trade_date=trade_date, input_dir=production_dir)
        _write_validation_report(validation_report, trade_date, staging_errors=legacy_errors, production_errors=production_errors)
        if production_errors:
            raise RuntimeError("production CSV validation failed: " + "; ".join(production_errors))

        if not args.skip_daily_report:
            report_input_dir = staging_dir if args.staging_canonical else production_dir
            _run_daily_report(trade_date, report_input_dir, reports_dir, artifacts_dir)
        _write_run_summary(run_summary, trade_date, "READY", production_dir, reports_dir, artifacts_dir, validation_report, fetch_summary, provider_health)
        _write_fetch_manifest(fetch_manifest, trade_date, "READY", staging_dir, production_dir, reports_dir, artifacts_dir, fetch_summary, provider_health, validation_report, allow_finmind_live=allow_finmind_live)
        validate_fetch_artifact_contract(trade_date=trade_date, outputs_dir=outputs_dir, reports_dir=reports_dir, staging_dir=staging_dir)
        _copy_if_exists(run_summary, outputs_summary)
    except Exception as exc:  # noqa: BLE001 - CLI must fail closed with exact blocking reason.
        _write_run_summary(run_summary, trade_date, "NOT_READY", production_dir, reports_dir, artifacts_dir, validation_report, fetch_summary, provider_health, blocking_error=str(exc))
        _ensure_fail_closed_diagnostic_artifacts(trade_date, fetch_summary, provider_health, blocking_error=str(exc), allow_finmind_live=_production_finmind_live_allowed(args.allow_finmind_live))
        _write_fetch_manifest(fetch_manifest, trade_date, "NOT_READY", staging_dir, production_dir, reports_dir, artifacts_dir, fetch_summary, provider_health, validation_report, allow_finmind_live=_production_finmind_live_allowed(args.allow_finmind_live), blocking_error=str(exc))
        try:
            validate_fetch_artifact_contract(trade_date=trade_date, outputs_dir=outputs_dir, reports_dir=reports_dir, staging_dir=staging_dir)
        except Exception as contract_exc:  # noqa: BLE001 - report artifact-contract failures as fail-closed diagnostics.
            print(f"ERROR GitHub Actions production fetch artifact contract failed: {contract_exc}", file=sys.stderr)
        _copy_if_exists(run_summary, outputs_summary)
        print(f"ERROR GitHub Actions production fetch failed closed: {exc}", file=sys.stderr)
        return 1

    print(f"GitHub Actions production fetch completed for {trade_date.isoformat()}")
    print(f"production_inputs: {production_dir}")
    print(f"reports: {reports_dir}")
    print(f"artifacts: {artifacts_dir}")
    print(f"fetch_manifest: {fetch_manifest}")
    return 0


def _production_finmind_live_allowed(cli_allowed: bool) -> bool:
    if cli_allowed:
        return True
    return os.environ.get("TDT_RM_ALLOW_FINMIND_LIVE", "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _run_fetchers(trade_date: date, staging_dir: Path, summary_path: Path, health_path: Path, source_config: str, allow_finmind_live: bool) -> None:
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "fetch_daily_data_multi_provider.py"),
        "--trade-date",
        trade_date.isoformat(),
        "--input-dir",
        str(staging_dir),
        "--summary-json",
        str(summary_path),
        "--provider-health-json",
        str(health_path),
        "--source-config",
        source_config,
        "--validate",
    ]
    if allow_finmind_live:
        if not (os.environ.get("FINMIND_TOKEN") or os.environ.get("FINMIND_API_TOKEN")):
            raise RuntimeError("FinMind fallback requested but FINMIND_TOKEN/FINMIND_API_TOKEN is missing")
        os.environ["TDT_RM_ALLOW_FINMIND_LIVE"] = "true"
        cmd.append("--allow-finmind-live")
    _run(cmd, "production provider fetchers")


def build_production_input_directory(*, trade_date: date, staging_dir: Path, production_dir: Path, fetch_summary_path: Path | None = None, provider_health_path: Path | None = None) -> None:
    """Create the required inputs/daily/YYYY-MM-DD production file set."""

    production_dir.mkdir(parents=True, exist_ok=True)
    copies = {
        "price.csv": "taiex_price.csv",
        "foreign_flow.csv": "twse_foreign_investor.csv",
        "breadth.csv": "twse_market_breadth.csv",
        "fx.csv": "fx_usdtwd.csv",
        "margin.csv": "twse_margin.csv",
    }
    materialized: dict[str, str] = {}
    for source_name, dest_name in copies.items():
        source = staging_dir / source_name
        if not source.exists():
            if source_name == "margin.csv":
                continue
            raise RuntimeError(f"required staged provider CSV missing: {source}")
        dest = production_dir / dest_name
        shutil.copyfile(source, dest)
        materialized[dest_name] = str(dest)

    _write_turnover_file(trade_date, staging_dir / "price.csv", production_dir / "twse_turnover_or_volume.csv")
    materialized["twse_turnover_or_volume.csv"] = str(production_dir / "twse_turnover_or_volume.csv")
    _write_taifex_combined_file(trade_date, staging_dir / "futures.csv", staging_dir / "options.csv", production_dir / "taifex_futures_options.csv")
    materialized["taifex_futures_options.csv"] = str(production_dir / "taifex_futures_options.csv")

    manifest = {
        "trade_date": trade_date.isoformat(),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "production_validity_rule": "fail_closed_required_csvs_schema_trade_date_source_type_no_stale_no_demo_mock_synthetic",
        "required_files": list(REQUIRED_PRODUCTION_FILES),
        "materialized_files": materialized,
        "staging_dir": str(staging_dir),
        "fetch_summary_path": str(fetch_summary_path) if fetch_summary_path else None,
        "provider_health_path": str(provider_health_path) if provider_health_path else None,
        "forbidden_source_types": sorted(FORBIDDEN_SOURCE_TYPES),
    }
    (production_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_required_production_files(*, trade_date: date, input_dir: Path) -> list[str]:
    errors: list[str] = []
    for filename in REQUIRED_PRODUCTION_FILES:
        path = input_dir / filename
        if not path.exists():
            errors.append(f"missing required production file: {path}")
            continue
        if filename == "manifest.json":
            errors.extend(_validate_manifest(path, trade_date))
            continue
        spec = CSV_SPECS[filename]
        errors.extend(_validate_csv(path, spec, trade_date))
    return errors


def _validate_manifest(path: Path, trade_date: date) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"manifest.json: cannot parse: {exc}"]
    errors = []
    if payload.get("trade_date") != trade_date.isoformat():
        errors.append(f"manifest.json: trade_date {payload.get('trade_date')!r} does not match {trade_date.isoformat()}")
    missing_declared = [name for name in REQUIRED_PRODUCTION_FILES if name not in payload.get("required_files", [])]
    if missing_declared:
        errors.append("manifest.json: required_files missing declarations: " + ", ".join(missing_declared))
    return errors


def _validate_csv(path: Path, spec: CsvSpec, trade_date: date) -> list[str]:
    errors: list[str] = []
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fieldnames = tuple(reader.fieldnames or ())
            rows = list(reader)
    except OSError as exc:
        return [f"{spec.filename}: cannot read CSV: {exc}"]
    if not rows:
        errors.append(f"{spec.filename}: row count must be > 0")
    missing = [column for column in spec.required_columns if column not in fieldnames]
    if missing:
        errors.append(f"{spec.filename}: missing required columns: {', '.join(missing)}")
    for index, row in enumerate(rows, start=2):
        if (row.get("trade_date") or row.get("date") or "").strip() != trade_date.isoformat():
            errors.append(f"{spec.filename}: line {index}: trade_date mismatch or stale data")
        provider_source = (row.get("provider_source") or "").strip()
        if not provider_source:
            errors.append(f"{spec.filename}: line {index}: provider_source is required")
        source_type = (row.get("source_type") or "").strip().lower()
        if not source_type:
            errors.append(f"{spec.filename}: line {index}: source_type is required")
        elif source_type in FORBIDDEN_SOURCE_TYPES:
            errors.append(f"{spec.filename}: line {index}: forbidden source_type {source_type!r}")
        for column in spec.numeric_columns:
            value = (row.get(column) or "").strip().replace(",", "")
            if value == "":
                errors.append(f"{spec.filename}: line {index}: numeric field {column} is blank")
                continue
            try:
                float(value)
            except ValueError:
                errors.append(f"{spec.filename}: line {index}: numeric field {column} is not parseable: {row.get(column)!r}")
        for column in spec.bool_columns:
            value = (row.get(column) or "").strip().lower()
            if value not in {"true", "false", "1", "0", "yes", "no", "y", "n"}:
                errors.append(f"{spec.filename}: line {index}: boolean field {column} is not parseable: {row.get(column)!r}")
    return errors


def _write_turnover_file(trade_date: date, price_path: Path, dest: Path) -> None:
    row = _read_single_row(price_path)
    _write_csv(dest, ("trade_date", "provider_source", "source_type", "turnover_amount"), {"trade_date": trade_date.isoformat(), "provider_source": row.get("provider_source"), "source_type": row.get("source_type"), "turnover_amount": row.get("turnover_amount")})


def _write_taifex_combined_file(trade_date: date, futures_path: Path, options_path: Path, dest: Path) -> None:
    futures = _read_single_row(futures_path)
    options = _read_single_row(options_path)
    provider_source = ";".join(filter(None, [futures.get("provider_source"), options.get("provider_source")]))
    source_type = futures.get("source_type") if futures.get("source_type") == options.get("source_type") else ";".join(filter(None, [futures.get("source_type"), options.get("source_type")]))
    row = {"trade_date": trade_date.isoformat(), "provider_source": provider_source, "source_type": source_type, **{key: futures.get(key) for key in ("futures_hedging_increases", "futures_hedging_significant", "futures_net_short_increases", "futures_net_short_decreases")}, **{key: options.get(key) for key in ("pcr_stable", "pcr_rises", "vix_stable", "vix_rises", "tail_risk")}}
    _write_csv(dest, CSV_SPECS["taifex_futures_options.csv"].required_columns + ("futures_net_short_increases", "futures_net_short_decreases"), row)



def _write_fetch_manifest(
    path: Path,
    trade_date: date,
    status: str,
    staging_dir: Path,
    production_dir: Path,
    reports_dir: Path,
    artifacts_dir: Path,
    fetch_summary_path: Path,
    provider_health_path: Path,
    validation_report_path: Path,
    *,
    allow_finmind_live: bool,
    blocking_error: str | None = None,
) -> None:
    fetch_summary = _load_json_if_exists(fetch_summary_path)
    provider_health = _load_json_if_exists(provider_health_path)
    validation_report = _load_json_if_exists(validation_report_path)
    provider_csv_paths = {dataset: str(staging_dir / f"{dataset}.csv") for dataset in REQUIRED_DATASETS if (staging_dir / f"{dataset}.csv").exists()}
    missing_datasets = _missing_datasets(fetch_summary, provider_csv_paths)
    validation_errors = validation_report.get("staging_validation", {}).get("errors", []) if isinstance(validation_report.get("staging_validation"), dict) else []
    production_errors = validation_report.get("production_validation", {}).get("errors", []) if isinstance(validation_report.get("production_validation"), dict) else []
    failed_sources = _failed_source_names(provider_health)
    payload = {
        "as_of": trade_date.isoformat(),
        "trade_date": trade_date.isoformat(),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "data_status": "READY" if status == "READY" and not missing_datasets and not validation_errors and not production_errors else "NOT_READY",
        "pipeline_status": "passed" if status == "READY" else "failed",
        "production_ready": bool(status == "READY" and not missing_datasets and not validation_errors and not production_errors),
        "official_source_first": True,
        "finmind_live_enabled": bool(allow_finmind_live),
        "finmind_fallback": _finmind_fallback_status(allow_finmind_live),
        "fail_closed": bool(status != "READY" or missing_datasets or validation_errors or production_errors),
        "blocking_error": blocking_error,
        "required_datasets": list(REQUIRED_DATASETS),
        "provider_csv_paths": provider_csv_paths,
        "missing_production_csvs": missing_datasets,
        "failed_sources": failed_sources,
        "stale_sources": [],
        "source_attempts": _source_attempts(fetch_summary, provider_health, staging_dir),
        "artifact_paths": {
            "production_inputs": str(production_dir),
            "reports": str(reports_dir),
            "artifacts": str(artifacts_dir),
            "production_fetch_summary": str(fetch_summary_path),
            "provider_health": str(provider_health_path),
            "validation_report": str(validation_report_path),
            "fetch_manifest": str(path),
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_fetch_artifact_contract(*, trade_date: date, outputs_dir: Path, reports_dir: Path, staging_dir: Path | None = None) -> list[str]:
    """Validate the GitHub Actions production-fetch artifact contract.

    READY runs must expose all staged provider CSVs plus machine-readable
    diagnostics. NOT_READY runs intentionally do not require CSVs, but still
    require diagnostics so fail-closed runs remain auditable.
    """

    artifacts_dir = reports_dir / "artifacts"
    manifest_path = outputs_dir / "fetch_manifest.json"
    fetch_summary_path = artifacts_dir / "production_fetch_summary.json"
    provider_health_path = artifacts_dir / "provider_health.json"
    errors: list[str] = []
    for path in (manifest_path, fetch_summary_path, provider_health_path):
        if not path.exists():
            errors.append(f"missing required diagnostic artifact: {path}")
    manifest = _load_json_if_exists(manifest_path)
    fetch_summary = _load_json_if_exists(fetch_summary_path)
    provider_health = _load_json_if_exists(provider_health_path)
    if manifest_path.exists() and not manifest:
        errors.append(f"required diagnostic artifact is not valid JSON object: {manifest_path}")
    if fetch_summary_path.exists() and not fetch_summary:
        errors.append(f"required diagnostic artifact is not valid JSON object: {fetch_summary_path}")
    if provider_health_path.exists() and not provider_health:
        errors.append(f"required diagnostic artifact is not valid JSON object: {provider_health_path}")
    if manifest:
        if manifest.get("as_of") != trade_date.isoformat() or manifest.get("trade_date") != trade_date.isoformat():
            errors.append(f"fetch_manifest.json trade_date/as_of must equal {trade_date.isoformat()}")
        data_status = str(manifest.get("data_status") or "")
        if data_status not in {"READY", "NOT_READY"}:
            errors.append("fetch_manifest.json data_status must be READY or NOT_READY")
        if data_status == "READY":
            provider_csv_paths = manifest.get("provider_csv_paths") if isinstance(manifest.get("provider_csv_paths"), Mapping) else {}
            for filename in REQUIRED_STAGED_CSVS:
                dataset = filename.removesuffix(".csv")
                candidates = []
                if staging_dir is not None:
                    candidates.append(staging_dir / filename)
                if provider_csv_paths.get(dataset):
                    candidates.append(Path(str(provider_csv_paths[dataset])))
                if not candidates or not any(path.exists() for path in candidates):
                    errors.append(f"READY artifact contract missing required staged CSV: {filename}")
        elif data_status == "NOT_READY":
            # Diagnostic JSON existence/parseability is checked above; CSVs are intentionally optional.
            pass
    if errors:
        raise RuntimeError("; ".join(errors))
    return []


def _ensure_fail_closed_diagnostic_artifacts(trade_date: date, fetch_summary_path: Path, provider_health_path: Path, *, blocking_error: str, allow_finmind_live: bool) -> None:
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if not provider_health_path.exists():
        provider_health_path.parent.mkdir(parents=True, exist_ok=True)
        provider_health_path.write_text(
            json.dumps(
                {
                    "as_of": trade_date.isoformat(),
                    "generated_at": generated_at,
                    "providers": {},
                    "summary": {
                        "total_providers": 0,
                        "healthy_providers": [],
                        "failed_providers": [],
                        "validation_failed": False,
                        "fail_closed": True,
                    },
                    "validation_errors": [],
                    "blocking_error": blocking_error,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    if not fetch_summary_path.exists():
        fetch_summary_path.parent.mkdir(parents=True, exist_ok=True)
        fetch_summary_path.write_text(
            json.dumps(
                {
                    "trade_date": trade_date.isoformat(),
                    "fetched_at": generated_at,
                    "overall_status": "NOT_READY",
                    "missing_datasets": [f"{dataset}.csv" for dataset in REQUIRED_DATASETS],
                    "validation_errors": [],
                    "provider_health_path": str(provider_health_path),
                    "provider_health_summary": _load_json_if_exists(provider_health_path).get("summary", {}),
                    "finmind_live_enabled": bool(allow_finmind_live),
                    "finmind_fallback": _finmind_fallback_status(allow_finmind_live),
                    "blocking_error": blocking_error,
                    "datasets": {},
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


def _finmind_fallback_status(allow_finmind_live: bool) -> dict[str, Any]:
    token_present = bool(os.environ.get("FINMIND_TOKEN"))
    api_token_present = bool(os.environ.get("FINMIND_API_TOKEN"))
    allowed = bool(allow_finmind_live)
    has_token = bool(token_present or api_token_present)
    return {
        "allow_finmind": allowed,
        "finmind_token_present": token_present,
        "finmind_api_token_present": api_token_present,
        "token_present": has_token,
        "fallback_skipped": not (allowed and has_token),
        "skip_reason": "" if allowed and has_token else (
            "missing FINMIND_TOKEN/FINMIND_API_TOKEN" if allowed else "allow_finmind false"
        ),
    }


def _missing_datasets(fetch_summary: Mapping[str, Any], provider_csv_paths: Mapping[str, str]) -> list[str]:
    summary_missing = fetch_summary.get("missing_datasets")
    if isinstance(summary_missing, list) and summary_missing:
        return [str(item).removesuffix(".csv") for item in summary_missing]
    return [dataset for dataset in REQUIRED_DATASETS if dataset not in provider_csv_paths]


def _source_attempts(fetch_summary: Mapping[str, Any], provider_health: Mapping[str, Any], staging_dir: Path | None = None) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    datasets = fetch_summary.get("datasets")
    health_by_dataset = _provider_health_attempts_by_dataset(provider_health)
    if isinstance(datasets, dict):
        for dataset, result in datasets.items():
            if not isinstance(result, dict):
                continue
            for health_attempt in health_by_dataset.get(str(dataset), []):
                attempts.append(_attempt_manifest_row(str(dataset), health_attempt, staging_dir))
            if health_by_dataset.get(str(dataset)):
                continue
            provider_used = result.get("provider_used")
            if provider_used:
                attempts.append(_attempt_manifest_row(str(dataset), {"provider": provider_used, "status": "healthy", "selected": True, "output_path": result.get("output_path")}, staging_dir))
            for failed in result.get("failed_providers", []) if isinstance(result.get("failed_providers"), list) else []:
                if isinstance(failed, dict):
                    attempts.append(_attempt_manifest_row(str(dataset), {"provider": failed.get("provider"), "status": "failed", "failure_reason": failed.get("message")}, staging_dir))
    providers = provider_health.get("providers")
    if not attempts and isinstance(providers, dict):
        for entry in providers.values():
            if not isinstance(entry, dict):
                continue
            dataset = str(entry.get("dataset") or "")
            for attempt in entry.get("attempts", []) if isinstance(entry.get("attempts"), list) else []:
                if isinstance(attempt, dict):
                    attempts.append(_attempt_manifest_row(dataset, attempt, staging_dir))
    return attempts


def _provider_health_attempts_by_dataset(provider_health: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    providers = provider_health.get("providers")
    if not isinstance(providers, dict):
        return grouped
    for entry in providers.values():
        if not isinstance(entry, dict):
            continue
        dataset = str(entry.get("dataset") or "")
        grouped.setdefault(dataset, [])
        for attempt in entry.get("attempts", []) if isinstance(entry.get("attempts"), list) else []:
            if isinstance(attempt, Mapping):
                grouped[dataset].append(attempt)
    return grouped


def _attempt_manifest_row(dataset: str, attempt: Mapping[str, Any], staging_dir: Path | None) -> dict[str, Any]:
    metadata = attempt.get("metadata") if isinstance(attempt.get("metadata"), Mapping) else {}
    url_fetch = metadata.get("url_fetch") if isinstance(metadata.get("url_fetch"), Mapping) else {}
    errors = url_fetch.get("errors") if isinstance(url_fetch.get("errors"), list) else []
    last_error = errors[-1] if errors and isinstance(errors[-1], Mapping) else {}
    status = str(attempt.get("status") or "")
    success = status == "healthy"
    output_path = attempt.get("output_path") if attempt.get("output_path") else (str(staging_dir / f"{dataset}.csv") if staging_dir and success else None)
    validation_errors = [str(check.get("message") or check.get("name")) for check in attempt.get("checks", []) if isinstance(check, Mapping) and check.get("status") not in {"passed", "success", True}]
    failure_reason = str(attempt.get("failure_reason") or last_error.get("error") or "")
    http_status = url_fetch.get("status") or last_error.get("status") or _http_status_from_message(failure_reason)
    endpoint = metadata.get("endpoint") or attempt.get("endpoint_attempted") or url_fetch.get("final_url") or url_fetch.get("initial_url") or last_error.get("url") or "not captured by provider adapter"
    rows_fetched = _csv_row_count(Path(str(output_path))) if output_path and success else int(metadata.get("bar_count") or 0)
    parser_status = "passed" if success else ("not_reached" if _classify_failure(failure_reason, http_status, rows_fetched, validation_errors) in {"network/proxy", "auth/token"} else "failed")
    validation_status = "passed" if success and not validation_errors else ("failed" if validation_errors else "not_reached")
    failure_class = "none" if success else _classify_failure(failure_reason, http_status, rows_fetched, validation_errors)
    failure_layer = "NONE" if success else _failure_layer(failure_reason, http_status, rows_fetched, validation_errors)
    return {
        "provider_category": dataset,
        "source_id": attempt.get("provider"),
        "source_type": str(metadata.get("source_type") or "provider"),
        "success": success,
        "selected": bool(attempt.get("selected")),
        "endpoint_attempted": endpoint,
        "http_status": http_status,
        "network_exception": str(url_fetch.get("network_exception") or last_error.get("network_exception") or _network_exception(failure_reason, http_status)),
        "rows_fetched": rows_fetched,
        "parser_status": parser_status,
        "validation_status": validation_status,
        "validation_errors": validation_errors,
        "failure_class": failure_class,
        "failure_layer": failure_layer,
        "error": failure_reason,
        "attempts": int(url_fetch.get("attempts") or attempt.get("attempts") or 0),
        "retry_attempts": int(url_fetch.get("attempts") or attempt.get("attempts") or 0),
        "output_path": output_path,
    }


def _http_status_from_message(message: str) -> int | None:
    import re

    match = re.search(r"\bHTTP\s+(\d{3})\b|status=(\d{3})", message)
    if not match:
        return None
    return int(match.group(1) or match.group(2))


def _network_exception(message: str, http_status: int | None) -> str:
    if http_status is not None:
        return ""
    lowered = message.lower()
    if any(token in lowered for token in ("tunnel connection failed", "url fetch failed", "timed out", "name or service", "connection", "network", "proxy")):
        return message
    return ""


def _classify_failure(message: str, http_status: int | None, rows_fetched: int, validation_errors: Sequence[str]) -> str:
    lowered = message.lower()
    if any(token in lowered for token in ("tunnel connection failed", "proxy", "url fetch failed", "timed out", "dns", "connection", "network")):
        return "network/proxy"
    if http_status in {401, 403} or "token" in lowered or "auth" in lowered or "unauthorized" in lowered or "forbidden" in lowered:
        return "auth/token"
    if validation_errors or "strict validation" in lowered or "schema" in lowered or "parse" in lowered:
        return "parser/schema"
    if rows_fetched == 0 or "no row" in lowered or "returned 0" in lowered or "insufficient" in lowered or "stale" in lowered:
        return "no-row"
    if "validation" in lowered or "reconciliation" in lowered:
        return "validator"
    return "unknown"


def _failure_layer(message: str, http_status: int | None, rows_fetched: int, validation_errors: Sequence[str]) -> str:
    """Map provider failure diagnostics to the production audit failure layer vocabulary."""

    lowered = message.lower()
    if not message and http_status is None and rows_fetched == 0 and not validation_errors:
        return "UNKNOWN"
    if "finmind" in lowered and ("disabled" in lowered or "opt-in" in lowered or "token" in lowered):
        return "CONFIG" if "disabled" in lowered or "opt-in" in lowered else "AUTH"
    if any(token in lowered for token in ("tunnel connection failed", "proxy", "url fetch failed", "timed out", "dns", "connection", "network")):
        return "NETWORK"
    if http_status in {401, 403} or "token" in lowered or "auth" in lowered or "unauthorized" in lowered or "forbidden" in lowered:
        return "AUTH"
    if "schema" in lowered or validation_errors or "strict validation" in lowered:
        return "SCHEMA"
    if "parse" in lowered or "no row" in lowered or "returned 0" in lowered or "insufficient" in lowered or "stale" in lowered:
        return "PARSER"
    return "WORKFLOW"


def _csv_row_count(path: Path) -> int:
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    except OSError:
        return 0


def _failed_source_names(provider_health: Mapping[str, Any]) -> list[str]:
    summary = provider_health.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("failed_providers"), list):
        return [str(item) for item in summary["failed_providers"]]
    return []


def _load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}

def _copy_if_exists(source: Path, dest: Path) -> None:
    if source.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)


def _mirror_directory(source: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    if source.exists():
        shutil.copytree(source, dest)


def _write_validation_report(path: Path, trade_date: date, *, staging_errors: Sequence[str], production_errors: Sequence[str]) -> None:
    payload = {
        "trade_date": trade_date.isoformat(),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "staging_validation": {"status": "passed" if not staging_errors else "failed", "errors": list(staging_errors)},
        "production_validation": {"status": "passed" if not production_errors else "failed", "errors": list(production_errors)},
        "overall_status": "passed" if not staging_errors and not production_errors else "failed",
        "fail_closed": bool(staging_errors or production_errors),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_run_summary(path: Path, trade_date: date, status: str, production_dir: Path, reports_dir: Path, artifacts_dir: Path, validation_report: Path, fetch_summary: Path, provider_health: Path, *, blocking_error: str | None = None) -> None:
    payload = {
        "trade_date": trade_date.isoformat(),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": status,
        "blocking_error": blocking_error,
        "artifact_paths": {
            "production_inputs": str(production_dir),
            "reports": str(reports_dir),
            "artifacts": str(artifacts_dir),
            "raw_provider_diagnostics": str(artifacts_dir / "raw"),
            "normalized_csvs": str(artifacts_dir / "normalized"),
            "production_snapshot_or_pipeline_outputs": str(artifacts_dir),
            "manifest": str(production_dir / "manifest.json"),
            "validation_report": str(validation_report),
            "fetch_summary": str(fetch_summary),
            "provider_health": str(provider_health),
            "run_summary": str(path),
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def _run_daily_report(trade_date: date, staging_dir: Path, reports_dir: Path, artifacts_dir: Path) -> None:
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "run_daily_production_pipeline.py"),
        "--trade-date",
        trade_date.isoformat(),
        "--input-dir",
        str(staging_dir),
        "--outputs-dir",
        str(artifacts_dir),
        "--reports-dir",
        str(reports_dir),
        "--pipeline-summary",
        str(artifacts_dir / "pipeline_summary.json"),
    ]
    _run(cmd, "TDT-RM daily production report")


def _read_single_row(path: Path) -> dict[str, str]:
    if not path.exists():
        raise RuntimeError(f"required CSV missing: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1:
        raise RuntimeError(f"{path} must contain exactly one row; got {len(rows)}")
    return dict(rows[0])


def _write_csv(path: Path, columns: Sequence[str], row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        writer.writerow({column: row.get(column, "") for column in columns})


def _run(cmd: Sequence[str], label: str) -> None:
    print("Running " + label + ": " + " ".join(cmd))
    completed = subprocess.run(cmd, cwd=REPO_ROOT, check=False, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"{label} failed with exit code {completed.returncode}")


if __name__ == "__main__":
    raise SystemExit(main())
