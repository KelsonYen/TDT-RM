#!/usr/bin/env python
"""Assemble a normalized TDT-RM daily market snapshot from local public-data rows."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tdt_rm.daily_providers import (  # noqa: E402
    DailyProviderContext,
    DailySnapshotAssembler,
    LocalCsvProvider,
    ManualScoreProvider,
    TAIEXPriceProvider,
)
from tdt_rm.daily_snapshot import build_source_coverage  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble an enriched TDT-RM DailyMarketSnapshot JSON.")
    parser.add_argument("--as-of", required=True, type=date.fromisoformat, help="Snapshot trade date, YYYY-MM-DD.")
    parser.add_argument("--output-json", required=True, help="Output path for normalized snapshot JSON.")
    parser.add_argument("--price-csv", help="Optional local TAIEX price bars or one-row derived price CSV.")
    parser.add_argument("--foreign-csv", help="Optional local foreign-flow CSV.")
    parser.add_argument("--fx-csv", help="Optional local USD/TWD or FX CSV.")
    parser.add_argument("--breadth-csv", help="Optional local market breadth CSV.")
    parser.add_argument("--margin-csv", help="Optional local margin/leverage CSV.")
    parser.add_argument("--scores-csv", help="Optional local formal Tail Risk, BCD, and MHS CSV.")
    parser.add_argument("--field-map", help="Optional JSON mapping file; may contain global or provider/category maps.")
    parser.add_argument("--validate", action="store_true", help="Exit non-zero on blocking snapshot validation errors.")
    parser.add_argument("--allow-warnings", action="store_true", help="Allow warning-only snapshots without a non-zero exit.")
    args = parser.parse_args()

    field_map, provider_maps = _load_field_maps(args.field_map)
    providers = []
    if args.price_csv:
        providers.append(TAIEXPriceProvider(source_path=args.price_csv))
    if args.foreign_csv:
        providers.append(LocalCsvProvider("foreign_flow_csv", "Local foreign-flow CSV", args.foreign_csv, "foreign_flow"))
    if args.fx_csv:
        providers.append(LocalCsvProvider("fx_csv", "Local FX CSV", args.fx_csv, "fx"))
    if args.breadth_csv:
        providers.append(LocalCsvProvider("breadth_csv", "Local breadth CSV", args.breadth_csv, "breadth"))
    if args.margin_csv:
        providers.append(LocalCsvProvider("margin_csv", "Local margin CSV", args.margin_csv, "margin"))
    if args.scores_csv:
        score_row = _load_score_row(args.scores_csv, args.as_of)
        providers.append(ManualScoreProvider("scores_csv", "Local manual/formal scores CSV", score_row))

    if not providers:
        raise SystemExit("at least one source file must be supplied")

    context = DailyProviderContext(as_of=args.as_of, field_map=field_map, provider_field_maps=provider_maps)
    result = DailySnapshotAssembler(providers).assemble(context)
    payload = result.snapshot.as_dict()
    payload["assembly"] = {
        "supplied_providers": [item.provider_id for item in result.provider_results],
        "provider_errors": list(result.provider_errors),
        "conflicts": list(result.conflicts),
        "missing_field_categories": list(result.missing_field_categories),
    }
    payload["validation"] = result.validation.as_dict()
    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    coverage = build_source_coverage(result.snapshot)
    print(f"trade_date: {result.snapshot.trade_date.isoformat()}")
    print(f"data_status: {result.snapshot.data_status}")
    print(f"supplied_providers: {', '.join(item.provider_id for item in result.provider_results) or 'none'}")
    print(f"missing_field_categories: {', '.join(result.missing_field_categories) or 'none'}")
    print(f"available_eti_components: {', '.join(coverage.available_eti_components) or 'none'}")
    print(f"tail_risk_source: {result.snapshot.field_sources.get('tail_risk', 'proxy/absent')}")
    print(f"bcd_source: {result.snapshot.field_sources.get('bcd', 'proxy/absent')}")
    print(f"warnings: {len(result.warnings)}")
    for warning in result.warnings:
        print(f"- {warning}")
    print(f"Snapshot: {output_path}")
    print(f"Validation: {'passed' if result.validation.is_valid else 'failed'}")

    if result.provider_errors:
        for error in result.provider_errors:
            print(f"ERROR {error}", file=sys.stderr)
        return 1
    if args.validate and not result.validation.is_valid:
        for issue in result.validation.issues:
            if issue.severity == "error":
                print(f"ERROR {issue.code}: {issue.message}", file=sys.stderr)
        return 1
    if args.validate and result.validation.issues and not args.allow_warnings:
        for issue in result.validation.issues:
            if issue.severity == "warning":
                print(f"WARNING {issue.code}: {issue.message}", file=sys.stderr)
        return 1
    return 0


def _load_field_maps(path: str | None) -> tuple[dict[str, str], dict[str, Mapping[str, str]]]:
    if not path:
        return {}, {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("--field-map must be a JSON object")
    provider_maps = payload.get("providers") or payload.get("provider_field_maps") or {}
    categories = payload.get("categories") or {}
    global_map = payload.get("global") or {}
    if not global_map:
        global_map = {key: value for key, value in payload.items() if isinstance(value, str)}
    scoped: dict[str, Mapping[str, str]] = {}
    for group in (provider_maps, categories):
        if isinstance(group, dict):
            for key, value in group.items():
                if isinstance(value, dict):
                    scoped[str(key)] = {str(k): str(v) for k, v in value.items()}
    return {str(key): str(value) for key, value in global_map.items()}, scoped


def _load_score_row(path: str, as_of: date) -> Mapping[str, Any]:
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return {}
    if len(rows) == 1:
        return rows[0]
    for row in rows:
        for key in ("observed_at", "trade_date", "date"):
            if row.get(key) and date.fromisoformat(str(row[key])[:10]) == as_of:
                return row
    return rows[-1]


if __name__ == "__main__":
    raise SystemExit(main())
