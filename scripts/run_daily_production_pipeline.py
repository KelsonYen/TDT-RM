#!/usr/bin/env python
"""Compatibility CLI for the daily production pipeline.

When ``--input-dir`` is supplied, this runner operates in local/import mode:
it validates and consumes committed CSV files only and never attempts live TWSE
or TAIFEX provider fetches.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tdt_rm.daily_pipeline import (  # noqa: E402
    render_operator_summary,
    render_report_task_summary,
    run_daily_pipeline,
    write_final_operator_reports,
    write_json_summary,
)
from validate_daily_input_csvs import SCHEMAS_BY_FILE, validate_daily_input_csvs  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run provider assembly, daily production scoring, and validation.")
    parser.add_argument("--trade-date", "--as-of", dest="as_of", required=True, type=date.fromisoformat, help="Trade date, YYYY-MM-DD.")
    parser.add_argument("--input-dir", "--inputs-dir", dest="inputs_dir", required=True, help="Directory containing local daily CSV inputs.")
    parser.add_argument("--outputs-dir", "--output-dir", dest="outputs_dir", help="Directory for production artifacts (default: <reports-dir>/artifacts).")
    parser.add_argument("--pipeline-summary", help="Optional pipeline summary JSON path (default: <outputs-dir>/pipeline_summary.json).")
    parser.add_argument("--snapshot-path", help="Optional pre-assembled daily market snapshot JSON.")
    parser.add_argument("--reports-dir", default="reports", help="Directory for dated operator report (default: reports).")
    args = parser.parse_args()

    inputs_dir = Path(args.inputs_dir)
    reports_dir = Path(args.reports_dir)
    outputs_dir = Path(args.outputs_dir) if args.outputs_dir else reports_dir / "artifacts"
    summary_path = Path(args.pipeline_summary) if args.pipeline_summary else outputs_dir / "pipeline_summary.json"

    try:
        strict_local_import = any(
            arg in {"--input-dir", "--inputs-dir"}
            or arg.startswith("--input-dir=")
            or arg.startswith("--inputs-dir=")
            for arg in sys.argv
        )
        if args.snapshot_path is None and strict_local_import:
            validation_errors = validate_daily_input_csvs(trade_date=args.as_of, input_dir=inputs_dir)
            if validation_errors:
                raise ValueError("daily input CSV validation failed: " + "; ".join(validation_errors))
            provider_paths = _local_input_paths(inputs_dir)
        elif args.snapshot_path is None:
            provider_paths = _legacy_provider_paths(inputs_dir, _load_manifest(inputs_dir))
        else:
            provider_paths = {}
        result = run_daily_pipeline(
            as_of=args.as_of,
            output_dir=outputs_dir,
            price_csv=provider_paths.get("price"),
            foreign_csv=provider_paths.get("foreign_flow"),
            fx_csv=provider_paths.get("fx"),
            breadth_csv=provider_paths.get("breadth"),
            futures_csv=provider_paths.get("futures"),
            options_csv=provider_paths.get("options"),
            leadership_csv=provider_paths.get("leadership"),
            margin_csv=provider_paths.get("margin"),
            field_map=provider_paths.get("field_map"),
            snapshot_path=args.snapshot_path,
            command="scripts/run_daily_production_pipeline.py",
        )
        write_json_summary(result, summary_path)
        report_paths = write_final_operator_reports(result, reports_dir)
        task_summary = render_report_task_summary(report_paths["latest"], result)
        if not strict_local_import:
            task_summary = task_summary.replace("TODAY\'S TDT-RM MARKET RESULT", "TODAY’S TDT-RM MARKET RESULT", 1)
    except Exception as exc:  # noqa: BLE001 - concise fail-closed CLI error.
        print(f"ERROR daily production pipeline failed: {exc}", file=sys.stderr)
        return 1

    print(render_operator_summary(result))
    print(f"pipeline_summary: {summary_path}")
    print()
    print(task_summary)
    return 0


def _local_input_paths(inputs_dir: Path) -> dict[str, str]:
    key_by_file = {
        "price.csv": "price",
        "foreign_flow.csv": "foreign_flow",
        "fx.csv": "fx",
        "breadth.csv": "breadth",
        "futures.csv": "futures",
        "options.csv": "options",
        "leadership.csv": "leadership",
        "margin.csv": "margin",
    }
    paths = {key: str(inputs_dir / name) for name, key in key_by_file.items() if (inputs_dir / name).exists() or name in SCHEMAS_BY_FILE}
    field_map = inputs_dir / "provider_field_map.json"
    if field_map.exists():
        paths["field_map"] = str(field_map)
    return paths


# Retained for callers that import these helpers from the compatibility module.
def _load_manifest(inputs_dir: Path) -> Mapping[str, Any]:
    path = inputs_dir / "fetch_manifest.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, Mapping) else {}


def _legacy_provider_paths(inputs_dir: Path, manifest: Mapping[str, Any]) -> dict[str, str]:
    paths: dict[str, str] = {}
    raw_paths = manifest.get("provider_csv_paths")
    if isinstance(raw_paths, Mapping):
        for key, value in raw_paths.items():
            if value:
                paths[str(key)] = str(value)
    defaults = {
        "price": "price.csv",
        "foreign_flow": "foreign_flow.csv",
        "fx": "fx.csv",
        "breadth": "breadth.csv",
        "leadership": "leadership.csv",
        "margin": "margin.csv",
        "scores": "scores.csv",
        "futures": "futures.csv",
        "options": "options.csv",
    }
    for key, filename in defaults.items():
        paths.setdefault(key, str(inputs_dir / filename))
    paths.setdefault("field_map", str(inputs_dir / "provider_field_map.json"))
    return {key: value for key, value in paths.items() if key == "field_map" or Path(value).exists()}


def _provider_paths(inputs_dir: Path, manifest: Mapping[str, Any]) -> dict[str, str]:
    return _legacy_provider_paths(inputs_dir, manifest)


if __name__ == "__main__":
    raise SystemExit(main())
