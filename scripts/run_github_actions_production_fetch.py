#!/usr/bin/env python
"""GitHub Actions production fetch orchestrator for TDT-RM.

This wrapper runs the live provider fetchers in a normal CI network, materializes
an auditable production input directory under inputs/daily/YYYY-MM-DD, validates
that no required production CSV is missing/stale/synthetic, and then runs the
existing daily production report from the strict provider CSVs.
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
    "taifex_futures_options.csv": CsvSpec("taifex_futures_options.csv", ("trade_date", "provider_source", "source_type", "futures_hedging_increases", "futures_hedging_significant", "pcr_stable", "pcr_rises", "vix_stable", "vix_rises", "tail_risk", "bcd"), ("tail_risk", "bcd"), ("futures_hedging_increases", "futures_hedging_significant", "pcr_stable", "pcr_rises", "vix_stable", "vix_rises")),
    "fx_usdtwd.csv": CsvSpec("fx_usdtwd.csv", ("trade_date", "provider_source", "source_type", "usd_twd_3d_change_pct", "usd_twd_5d_change_pct"), ("usd_twd_3d_change_pct", "usd_twd_5d_change_pct")),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the GitHub Actions production data-fetch pipeline.")
    parser.add_argument("--trade-date", required=True, type=date.fromisoformat, help="Trade date YYYY-MM-DD.")
    parser.add_argument("--inputs-root", default="inputs/daily", help="Root for production input directories.")
    parser.add_argument("--reports-root", default="reports/daily", help="Root for dated production reports.")
    parser.add_argument("--source-config", default="config/public_data_sources.json", help="Public provider source configuration.")
    parser.add_argument("--allow-finmind-live", action="store_true", help="Allow FinMind only as an explicit token-gated vendor fallback.")
    parser.add_argument("--skip-fetch", action="store_true", help="Testing hook: do not call live providers; consume an existing staging directory.")
    parser.add_argument("--staging-dir", help="Strict provider CSV staging dir (default: inputs/daily/<date>/_strict_provider_csvs).")
    args = parser.parse_args()

    trade_date = args.trade_date
    production_dir = REPO_ROOT / args.inputs_root / trade_date.isoformat()
    staging_dir = Path(args.staging_dir) if args.staging_dir else production_dir / "_strict_provider_csvs"
    reports_dir = REPO_ROOT / args.reports_root / trade_date.isoformat()
    artifacts_dir = reports_dir / "artifacts"
    fetch_summary = artifacts_dir / "production_fetch_summary.json"
    provider_health = artifacts_dir / "provider_health.json"
    raw_dir = artifacts_dir / "raw"
    normalized_dir = artifacts_dir / "normalized"
    validation_report = artifacts_dir / "validation_report.json"
    run_summary = artifacts_dir / "run_summary.json"

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir.mkdir(parents=True, exist_ok=True)

    try:
        if not args.skip_fetch:
            _run_fetchers(trade_date, staging_dir, fetch_summary, provider_health, args.source_config, args.allow_finmind_live)
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

        _run_daily_report(trade_date, staging_dir, reports_dir, artifacts_dir)
        _write_run_summary(run_summary, trade_date, "READY", production_dir, reports_dir, artifacts_dir, validation_report, fetch_summary, provider_health)
    except Exception as exc:  # noqa: BLE001 - CLI must fail closed with exact blocking reason.
        _write_run_summary(run_summary, trade_date, "NOT_READY", production_dir, reports_dir, artifacts_dir, validation_report, fetch_summary, provider_health, blocking_error=str(exc))
        print(f"ERROR GitHub Actions production fetch failed closed: {exc}", file=sys.stderr)
        return 1

    print(f"GitHub Actions production fetch completed for {trade_date.isoformat()}")
    print(f"production_inputs: {production_dir}")
    print(f"reports: {reports_dir}")
    print(f"artifacts: {artifacts_dir}")
    return 0


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
        if not os.environ.get("FINMIND_TOKEN"):
            raise RuntimeError("FINMIND_TOKEN secret is required before enabling FinMind fallback")
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
    row = {"trade_date": trade_date.isoformat(), "provider_source": provider_source, "source_type": source_type, **{key: futures.get(key) for key in ("futures_hedging_increases", "futures_hedging_significant", "futures_net_short_increases", "futures_net_short_decreases")}, **{key: options.get(key) for key in ("pcr_stable", "pcr_rises", "vix_stable", "vix_rises", "tail_risk", "bcd")}}
    _write_csv(dest, CSV_SPECS["taifex_futures_options.csv"].required_columns + ("futures_net_short_increases", "futures_net_short_decreases"), row)



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
