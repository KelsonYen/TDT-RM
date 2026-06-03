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
    parser.add_argument("--as-of", "--trade-date", dest="as_of", required=True, type=date.fromisoformat, help="Target trade date, YYYY-MM-DD.")
    parser.add_argument("--output-dir", "--outputs-dir", dest="output_dir", required=True, help="Directory for generated provider CSVs and fetch manifest.")
    parser.add_argument("--source-config", help="Optional JSON/YAML source configuration.")
    parser.add_argument("--main7-config", help="Optional JSON file containing a Main-7 symbols list.")
    parser.add_argument("--allow-partial", action="store_true", help="Allow a run when optional public sources are unavailable; price remains required for pipeline runs.")
    parser.add_argument("--run-pipeline", action="store_true", help="Run scripts/run_daily_pipeline.py logic with generated provider CSVs.")
    parser.add_argument("--pipeline-output-dir", default="outputs/daily", help="Directory for daily production artifacts when --run-pipeline is supplied.")
    parser.add_argument("--json-summary", help="Optional path for a machine-readable combined summary JSON.")
    parser.add_argument("--price-fallback-csv", help="Optional local canonical price CSV fallback. Used after live price failures or immediately with --offline.")
    parser.add_argument("--price-fallback-json", help="Optional local canonical price JSON fallback. Used after live price failures or immediately with --offline.")
    parser.add_argument("--offline", action="store_true", help="Skip live network sources and use only configured/local fallback files.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop a provider category after its first failed source instead of trying configured fallbacks.")
    parser.add_argument("--cache-dir", help="Optional local provider cache directory for successful fetch results.")
    parser.add_argument("--cache-mode", choices=("off", "read", "write", "read_write", "replay"), default="off", help="Provider cache mode. replay is an alias for read-only historical replay.")
    parser.add_argument("--use-cache", action="store_true", help="Compatibility alias: use inputs/provider_cache in read_write mode unless --cache-dir/--cache-mode override it.")
    args = parser.parse_args()

    if args.use_cache:
        if not args.cache_dir:
            args.cache_dir = "inputs/provider_cache"
        if args.cache_mode == "off":
            args.cache_mode = "read_write"

    try:
        source_config = load_source_config(args.source_config)
        _add_runtime_price_fallback_sources(source_config, args.price_fallback_csv, args.price_fallback_json)
        main7_symbols = load_main7_symbols(args.main7_config)
        registry = PublicDataFetcherRegistry.from_config(source_config)
        context = PublicDataFetchContext(as_of=args.as_of, source_config=source_config, main7_symbols=main7_symbols, offline=args.offline, fail_fast=args.fail_fast, cache_dir=args.cache_dir, cache_mode=args.cache_mode)
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
        _print_price_failure_diagnostics(write_result.manifest, args, file=sys.stderr)
        _maybe_write_json_summary(args.json_summary, {"fetch": write_result.as_dict(), "pipeline": None, "blocking_error": "price provider unavailable"})
        return 0 if args.allow_partial and not args.run_pipeline else 1
    missing_production_csvs = [str(item) for item in manifest.get("missing_production_csvs", [])] if isinstance(manifest.get("missing_production_csvs"), list) else []
    if missing_production_csvs and not args.allow_partial:
        print("ERROR production provider CSVs missing without --allow-partial: " + ", ".join(missing_production_csvs), file=sys.stderr)
        _maybe_write_json_summary(args.json_summary, {"fetch": write_result.as_dict(), "pipeline": None, "blocking_error": "production provider CSVs missing"})
        return 1
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


def _add_runtime_price_fallback_sources(source_config: dict[str, object], csv_path: str | None, json_path: str | None) -> None:
    sources = source_config.setdefault("sources", [])
    if not isinstance(sources, list):
        source_config["sources"] = sources = []
    next_order = 10_000
    existing_orders = [item.get("fallback_order") for item in sources if isinstance(item, dict)]
    numeric_orders = []
    for value in existing_orders:
        try:
            numeric_orders.append(int(value))
        except (TypeError, ValueError):
            pass
    if numeric_orders:
        next_order = max(numeric_orders) + 10
    if csv_path:
        sources.append(_runtime_price_fallback_source("cli_price_fallback_csv", "local_csv_fallback", csv_path, next_order))
        next_order += 10
    if json_path:
        sources.append(_runtime_price_fallback_source("cli_price_fallback_json", "local_json_fallback", json_path, next_order))


def _runtime_price_fallback_source(source_id: str, source_type: str, path: str, fallback_order: int) -> dict[str, object]:
    return {
        "source_id": source_id,
        "source_name": "CLI local price fallback " + ("CSV" if source_type == "local_csv_fallback" else "JSON"),
        "provider_category": "price",
        "adapter": "local_price_fallback",
        "source_type": source_type,
        "enabled": True,
        "fallback_order": fallback_order,
        "path": path,
        "freshness_rules": {"max_lag_days": 0},
        "notes": "Runtime user-supplied local fallback; treated as external data and validated against --as-of before writing price.csv.",
        "limitations": "Not production market data unless the operator supplies an externally downloaded official/vendor file.",
    }


def _print_price_failure_diagnostics(manifest: dict[str, object], args: argparse.Namespace, *, file) -> None:
    print("ERROR required provider price failed (price provider unavailable)", file=file)
    print("attempted sources:", file=file)
    attempts = manifest.get("source_attempts", [])
    price_attempts = [item for item in attempts if isinstance(item, dict) and item.get("provider_category") == "price"] if isinstance(attempts, list) else []
    if not price_attempts:
        print("  - none (offline mode may have skipped live sources and no local fallback was configured)", file=file)
    for attempt in price_attempts:
        source_id = attempt.get("source_id")
        status = attempt.get("status")
        reason = attempt.get("failure_reason") or "no detailed failure reason recorded"
        print(f"  - {source_id}: status={status}; failure_reason={reason}", file=file)
    print("suggested fallback command:", file=file)
    print(
        "  python scripts/fetch_daily_provider_csvs.py "
        f"--as-of {args.as_of.isoformat()} --output-dir {args.output_dir} "
        "--price-fallback-csv path/to/price.csv --allow-partial",
        file=file,
    )


def _maybe_write_json_summary(path: str | None, summary: dict[str, object]) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
