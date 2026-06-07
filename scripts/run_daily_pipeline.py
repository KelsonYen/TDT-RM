#!/usr/bin/env python
"""CLI entrypoint for the one-command TDT-RM daily production pipeline."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tdt_rm.daily_pipeline import render_operator_summary, run_daily_pipeline, write_json_summary  # noqa: E402
from tdt_rm.daily_runner import DEFAULT_OUTPUT_DIR  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run provider assembly, daily production, validation, and operator summary.")
    parser.add_argument("--as-of", required=True, type=date.fromisoformat, help="Daily pipeline trade/validation date, YYYY-MM-DD.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for daily artifacts.")
    parser.add_argument("--snapshot-out", help="Optional path for the assembled snapshot JSON.")
    parser.add_argument("--price-csv", help="Required local price CSV unless --snapshot-path is supplied.")
    parser.add_argument("--foreign-csv", help="Optional local foreign-flow CSV.")
    parser.add_argument("--fx-csv", help="Optional local FX CSV.")
    parser.add_argument("--breadth-csv", help="Optional local market breadth CSV.")
    parser.add_argument("--leadership-csv", help="Optional local leadership/mainstream stock CSV.")
    parser.add_argument("--margin-csv", help="Optional local margin/leverage CSV.")
    parser.add_argument("--scores-csv", help="Optional local formal Tail Risk, BCD, and MHS CSV.")
    parser.add_argument("--futures-csv", help="Optional local futures CSV.")
    parser.add_argument("--options-csv", help="Optional local options CSV.")
    parser.add_argument("--field-map", help="Optional JSON mapping file for provider/category fields.")
    parser.add_argument("--snapshot-path", help="Existing enriched daily snapshot JSON; skips provider assembly.")
    parser.add_argument("--allow-warnings", action="store_true", help="Surface warning-only results without adding stricter blocking rules.")
    parser.add_argument("--no-manifest", action="store_true", help="Do not write the daily production manifest JSON.")
    parser.add_argument("--json-summary", help="Optional path for a machine-readable pipeline summary JSON.")
    args = parser.parse_args()

    try:
        result = run_daily_pipeline(
            as_of=args.as_of,
            output_dir=args.output_dir,
            snapshot_out=args.snapshot_out,
            price_csv=args.price_csv,
            foreign_csv=args.foreign_csv,
            fx_csv=args.fx_csv,
            breadth_csv=args.breadth_csv,
            leadership_csv=args.leadership_csv,
            margin_csv=args.margin_csv,
            scores_csv=args.scores_csv,
            futures_csv=args.futures_csv,
            options_csv=args.options_csv,
            field_map=args.field_map,
            snapshot_path=args.snapshot_path,
            write_manifest=not args.no_manifest,
            command="scripts/run_daily_pipeline.py",
        )
    except Exception as exc:  # noqa: BLE001 - CLI should present concise operator error.
        print(f"ERROR {exc}", file=sys.stderr)
        return 1

    if args.json_summary:
        write_json_summary(result, args.json_summary)
    print(render_operator_summary(result))

    validation = result.get("validation", {})
    if isinstance(validation, dict) and validation.get("has_errors"):
        return 1
    if isinstance(validation, dict) and validation.get("error_count"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
