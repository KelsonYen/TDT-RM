#!/usr/bin/env python
"""Replay cached provider data across a historical date range."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tdt_rm.daily_pipeline import run_daily_pipeline  # noqa: E402
from tdt_rm.public_data_fetchers import (  # noqa: E402
    PublicDataFetchContext,
    PublicDataFetcherRegistry,
    load_main7_symbols,
    load_source_config,
    write_provider_csvs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay TDT-RM daily runs from the local provider cache.")
    parser.add_argument("--start", required=True, type=date.fromisoformat, help="First replay date, YYYY-MM-DD.")
    parser.add_argument("--end", required=True, type=date.fromisoformat, help="Last replay date, YYYY-MM-DD.")
    parser.add_argument("--cache-dir", required=True, help="Provider cache directory populated by --cache-mode write/read_write.")
    parser.add_argument("--output-dir", required=True, help="Directory for replay provider CSVs and replay_summary.json.")
    parser.add_argument("--source-config", help="Source configuration used to compute cache keys.")
    parser.add_argument("--main7-config", help="Optional JSON file containing a Main-7 symbols list.")
    parser.add_argument("--run-pipeline", action="store_true", help="Run the daily pipeline for each replayed date with cached provider CSVs.")
    parser.add_argument("--pipeline-output-dir", default="outputs/replay", help="Directory for replayed daily artifacts.")
    args = parser.parse_args()

    if args.end < args.start:
        print("ERROR --end must be on or after --start", file=sys.stderr)
        return 1

    source_config = load_source_config(args.source_config)
    main7_symbols = load_main7_symbols(args.main7_config)
    registry = PublicDataFetcherRegistry.from_config(source_config)
    rows: list[dict[str, Any]] = []
    failed = False

    for as_of in _date_range(args.start, args.end):
        day_dir = Path(args.output_dir) / as_of.isoformat()
        context = PublicDataFetchContext(
            as_of=as_of,
            source_config=source_config,
            main7_symbols=main7_symbols,
            offline=True,
            cache_dir=args.cache_dir,
            cache_mode="read",
        )
        results = registry.fetch_all(context)
        written = write_provider_csvs(results, day_dir, as_of)
        row: dict[str, Any] = {
            "as_of": as_of.isoformat(),
            "data_status": written.data_status,
            "provider_csv_paths": dict(written.provider_csv_paths),
            "fetch_manifest_path": written.fetch_manifest_path,
            "pipeline": None,
        }
        if "price" not in written.provider_csv_paths:
            row["blocking_error"] = "price provider cache unavailable"
            failed = True
        elif args.run_pipeline:
            try:
                row["pipeline"] = run_daily_pipeline(
                    as_of=as_of,
                    output_dir=Path(args.pipeline_output_dir) / as_of.isoformat(),
                    price_csv=written.provider_csv_paths.get("price"),
                    foreign_csv=written.provider_csv_paths.get("foreign_flow"),
                    fx_csv=written.provider_csv_paths.get("fx"),
                    breadth_csv=written.provider_csv_paths.get("breadth"),
                    leadership_csv=written.provider_csv_paths.get("leadership"),
                    margin_csv=written.provider_csv_paths.get("margin"),
                    scores_csv=written.provider_csv_paths.get("scores"),
                    field_map=written.provider_field_map_path,
                    command="scripts/replay_daily_provider_cache.py --run-pipeline",
                )
            except Exception as exc:  # noqa: BLE001 - replay records per-day failures.
                row["blocking_error"] = str(exc)
                failed = True
        rows.append(row)

    summary = {
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "cache_dir": args.cache_dir,
        "run_pipeline": args.run_pipeline,
        "days": rows,
        "failed_days": [row["as_of"] for row in rows if row.get("blocking_error")],
    }
    out = Path(args.output_dir) / "replay_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"replay_summary": str(out), "failed_days": summary["failed_days"]}, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if failed else 0


def _date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


if __name__ == "__main__":
    raise SystemExit(main())
