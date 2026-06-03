#!/usr/bin/env python
"""Compatibility CLI for the daily production pipeline.

This wrapper preserves the operator-facing ``run_daily_production_pipeline.py``
command while delegating all scoring and validation work to the existing
production pipeline implementation.  It performs no model-logic changes.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tdt_rm.daily_pipeline import (  # noqa: E402
    render_operator_summary,
    render_report_task_summary,
    run_daily_pipeline,
    write_final_operator_reports,
    write_json_summary,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run provider assembly, daily production scoring, and validation.")
    parser.add_argument("--trade-date", "--as-of", dest="as_of", required=True, type=date.fromisoformat, help="Trade date, YYYY-MM-DD.")
    parser.add_argument("--inputs-dir", required=True, help="Directory containing provider CSVs and fetch_manifest.json.")
    parser.add_argument("--outputs-dir", "--output-dir", dest="outputs_dir", required=True, help="Directory for production artifacts.")
    parser.add_argument("--pipeline-summary", help="Optional pipeline summary JSON path (default: <outputs-dir>/pipeline_summary.json).")
    parser.add_argument("--snapshot-path", help="Optional pre-assembled daily market snapshot JSON.")
    parser.add_argument("--reports-dir", default="reports", help="Directory for dated and latest final operator reports (default: reports).")
    args = parser.parse_args()

    inputs_dir = Path(args.inputs_dir)
    outputs_dir = Path(args.outputs_dir)
    summary_path = Path(args.pipeline_summary) if args.pipeline_summary else outputs_dir / "pipeline_summary.json"

    try:
        manifest = _load_manifest(inputs_dir)
        provider_paths = _provider_paths(inputs_dir, manifest)
        result = run_daily_pipeline(
            as_of=args.as_of,
            output_dir=outputs_dir,
            price_csv=provider_paths.get("price"),
            foreign_csv=provider_paths.get("foreign_flow"),
            fx_csv=provider_paths.get("fx"),
            breadth_csv=provider_paths.get("breadth"),
            leadership_csv=provider_paths.get("leadership"),
            margin_csv=provider_paths.get("margin"),
            scores_csv=provider_paths.get("scores"),
            field_map=provider_paths.get("field_map"),
            snapshot_path=args.snapshot_path,
            command="scripts/run_daily_production_pipeline.py",
        )
        write_json_summary(result, summary_path)
        report_paths = write_final_operator_reports(result, args.reports_dir)
        task_summary = render_report_task_summary(report_paths["latest"], result)
    except Exception as exc:  # noqa: BLE001 - concise fail-closed CLI error.
        print(f"ERROR daily production pipeline failed: {exc}", file=sys.stderr)
        return 1

    print(render_operator_summary(result))
    print(f"pipeline_summary: {summary_path}")
    print()
    print(task_summary)
    return 0


def _load_manifest(inputs_dir: Path) -> Mapping[str, Any]:
    path = inputs_dir / "fetch_manifest.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, Mapping) else {}


def _provider_paths(inputs_dir: Path, manifest: Mapping[str, Any]) -> dict[str, str]:
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
    }
    for key, filename in defaults.items():
        paths.setdefault(key, str(inputs_dir / filename))
    paths.setdefault("field_map", str(inputs_dir / "provider_field_map.json"))
    return {key: value for key, value in paths.items() if key == "field_map" or Path(value).exists()}


if __name__ == "__main__":
    raise SystemExit(main())
