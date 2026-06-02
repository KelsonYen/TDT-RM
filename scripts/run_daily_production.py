#!/usr/bin/env python
"""CLI entrypoint for the TDT-RM V5.1.4 daily production runner."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tdt_rm.daily_runner import DEFAULT_OUTPUT_DIR, run_daily_production


def main() -> int:
    parser = argparse.ArgumentParser(description="Run TDT-RM V5.1.4 daily production scoring.")
    parser.add_argument("--as-of", type=date.fromisoformat, help="Download data up to this YYYY-MM-DD date.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for daily JSON, Markdown, and manifest artifacts (default: outputs/daily).",
    )
    parser.add_argument(
        "--no-manifest",
        action="store_true",
        help="Do not write the daily production validation manifest JSON.",
    )
    args = parser.parse_args()

    result = run_daily_production(
        as_of=args.as_of,
        output_dir=args.output_dir,
        write_manifest=not args.no_manifest,
        command="scripts/run_daily_production.py",
    )
    print(f"JSON: {result.json_path}")
    print(f"Markdown: {result.markdown_path}")
    if result.manifest_path is not None:
        print(f"Manifest: {result.manifest_path}")
    print(f"Signal: {result.payload['signal']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
