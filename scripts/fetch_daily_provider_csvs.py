#!/usr/bin/env python
"""Fetch public daily data and generate provider CSVs for TDT-RM."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tdt_rm.daily_pipeline import render_operator_summary, run_daily_pipeline, write_json_summary  # noqa: E402
from tdt_rm.public_data_fetchers import (  # noqa: E402
    PublicDataFetchContext,
    PublicDataFetcherRegistry,
    load_main7_symbols,
    load_source_config,
    write_provider_csvs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate provider CSVs from public data, optionally run the daily pipeline.")
    parser.add_argument("--as-of", required=True, type=date.fromisoformat, help="Target trade date, YYYY-MM-DD.")
    parser.add_argument("--output-dir", required=True, help="Directory for generated provider CSVs and fetch manifest.")
    parser.add_argument("--source-config", help="Optional JSON/YAML source configuration.")
    parser.add_argument("--main7-config", help="Optional JSON file containing a Main-7 symbols list.")
    parser.add_argument("--allow-partial", action="store_true", help="Allow a run when optional public sources are unavailable; price remains required for pipeline runs.")
    parser.add_argument("--run-pipeline", action="store_true", help="Run scripts/run_daily_pipeline.py logic with generated provider CSVs.")
    parser.add_argument("--pipeline-output-dir", default="outputs/daily", help="Directory for daily production artifacts when --run-pipeline is supplied.")
    parser.add_argument("--json-summary", help="Optional path for a machine-readable combined summary JSON.")
    args = parser.parse_args()

    try:
        source_config = load_source_config(args.source_config)
        main7_symbols = load_main7_symbols(args.main7_config)
        registry = PublicDataFetcherRegistry.from_config(source_config)
        context = PublicDataFetchContext(as_of=args.as_of, source_config=source_config, main7_symbols=main7_symbols)
        fetch_results = registry.fetch_all(context)
        write_result = write_provider_csvs(fetch_results, args.output_dir, args.as_of)
    except Exception as exc:  # noqa: BLE001 - concise CLI error.
        print(f"ERROR {exc}", file=sys.stderr)
        return 1

    manifest = dict(write_result.manifest)
    provider_paths = dict(write_result.provider_csv_paths)
    price_available = "price" in provider_paths
    failed_optional = [
        result.source_id
        for result in fetch_results
        if result.provider_category != "price" and not result.success
    ]

    if not price_available:
        print("ERROR price provider unavailable; cannot run a full TDT-RM daily production pipeline.", file=sys.stderr)
        _maybe_write_json_summary(args.json_summary, {"fetch": write_result.as_dict(), "pipeline": None, "blocking_error": "price provider unavailable"})
        return 0 if args.allow_partial and not args.run_pipeline else 1
    if failed_optional and not args.allow_partial:
        print("ERROR optional public sources unavailable without --allow-partial: " + ", ".join(failed_optional), file=sys.stderr)
        _maybe_write_json_summary(args.json_summary, {"fetch": write_result.as_dict(), "pipeline": None, "blocking_error": "optional sources unavailable without --allow-partial"})
        return 1

    pipeline_result = None
    if args.run_pipeline:
        try:
            pipeline_result = run_daily_pipeline(
                as_of=args.as_of,
                output_dir=args.pipeline_output_dir,
                price_csv=provider_paths.get("price"),
                foreign_csv=provider_paths.get("foreign_flow"),
                fx_csv=provider_paths.get("fx"),
                breadth_csv=provider_paths.get("breadth"),
                leadership_csv=provider_paths.get("leadership"),
                margin_csv=provider_paths.get("margin"),
                scores_csv=provider_paths.get("scores"),
                field_map=write_result.provider_field_map_path,
                command="scripts/fetch_daily_provider_csvs.py --run-pipeline",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR daily pipeline failed: {exc}", file=sys.stderr)
            _maybe_write_json_summary(args.json_summary, {"fetch": write_result.as_dict(), "pipeline": None, "blocking_error": str(exc)})
            return 1
        print(render_operator_summary(pipeline_result))

    summary = {"fetch": write_result.as_dict(), "pipeline": pipeline_result}
    _maybe_write_json_summary(args.json_summary, summary)
    if not args.run_pipeline:
        print(json.dumps({"data_status": manifest.get("data_status"), "provider_csv_paths": provider_paths, "fetch_manifest": write_result.fetch_manifest_path}, ensure_ascii=False, indent=2, sort_keys=True))
    if pipeline_result and isinstance(pipeline_result.get("validation"), dict) and pipeline_result["validation"].get("has_errors"):
        return 1
    return 0


def _maybe_write_json_summary(path: str | None, summary: dict[str, object]) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
