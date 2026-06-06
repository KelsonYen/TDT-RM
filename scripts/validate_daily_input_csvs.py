#!/usr/bin/env python
"""Validate committed daily input CSVs for local TDT-RM ingestion."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

FORBIDDEN_SOURCE_TYPES = {"fallback", "mock", "fixture", "synthetic", "neutral", "sample", "test"}
FORBIDDEN_PROVIDER_BCD_FIELDS = {"bcd", "BCD", "bcd_score", "provider_bcd", "bcd_final_score", "bcd_status"}
PROVIDER_BCD_FORBIDDEN_MESSAGE = "Provider-supplied BCD is forbidden. BCD must be computed only by score_bcd(BCDInput(…))."
COMMON_COLUMNS = {
    "trade_date": "date",
    "provider_source": "string",
    "source_type": "string",
}


@dataclass(frozen=True)
class CsvSchema:
    filename: str
    required_columns: tuple[str, ...]
    numeric_columns: tuple[str, ...] = ()
    bool_columns: tuple[str, ...] = ()


SCHEMAS: tuple[CsvSchema, ...] = (
    CsvSchema(
        "price.csv",
        ("trade_date", "provider_source", "source_type", "close", "ma5", "ma20", "ma60", "ma20_slope", "one_day_return_pct", "two_day_return_pct", "close_below_ma20_consecutive_days", "index_5d_return_pct", "return_60d_pct", "previous_ma60", "turnover_amount"),
        ("close", "ma5", "ma20", "ma60", "ma20_slope", "one_day_return_pct", "two_day_return_pct", "close_below_ma20_consecutive_days", "index_5d_return_pct", "return_60d_pct", "previous_ma60", "turnover_amount"),
    ),
    CsvSchema(
        "foreign_flow.csv",
        ("trade_date", "provider_source", "source_type", "foreign_spot_net_buy", "foreign_spot_net_sell", "foreign_spot_net_sell_consecutive_days", "foreign_spot_large_sell", "foreign_large_sell"),
        ("foreign_spot_net_buy", "foreign_spot_net_sell", "foreign_spot_net_sell_consecutive_days"),
        ("foreign_spot_large_sell", "foreign_large_sell"),
    ),
    CsvSchema(
        "fx.csv",
        ("trade_date", "provider_source", "source_type", "usd_twd_3d_change_pct", "usd_twd_5d_change_pct", "twd_appreciates", "twd_stable", "twd_depreciates_significantly"),
        ("usd_twd_3d_change_pct", "usd_twd_5d_change_pct"),
        ("twd_appreciates", "twd_stable", "twd_depreciates_significantly"),
    ),
    CsvSchema(
        "breadth.csv",
        ("trade_date", "provider_source", "source_type", "index_down", "advancing_issues", "declining_issues", "declining_issues_significantly_expand", "declining_issues_significantly_gt_advancing", "declining_gt_advancing_consecutive_days", "breadth_weakens_for_2_days"),
        ("advancing_issues", "declining_issues", "declining_gt_advancing_consecutive_days"),
        ("index_down", "declining_issues_significantly_expand", "declining_issues_significantly_gt_advancing", "breadth_weakens_for_2_days"),
    ),
    CsvSchema(
        "futures.csv",
        ("trade_date", "provider_source", "source_type", "futures_hedging_increases", "futures_hedging_significant", "futures_net_short_increases", "futures_net_short_decreases"),
        (),
        ("futures_hedging_increases", "futures_hedging_significant", "futures_net_short_increases", "futures_net_short_decreases"),
    ),
    CsvSchema(
        "options.csv",
        ("trade_date", "provider_source", "source_type", "pcr_stable", "pcr_rises", "vix_stable", "vix_rises", "tail_risk"),
        ("tail_risk",),
        ("pcr_stable", "pcr_rises", "vix_stable", "vix_rises"),
    ),
    CsvSchema(
        "leadership.csv",
        ("trade_date", "provider_source", "source_type", "count_main_7_below_ma20", "count_main_7_below_ma60", "majority_main_7_assets_above_ma20", "main_7_symbols", "main_7_below_ma20_symbols", "mhs"),
        ("count_main_7_below_ma20", "count_main_7_below_ma60", "mhs"),
        ("majority_main_7_assets_above_ma20",),
    ),
    CsvSchema(
        "margin.csv",
        ("trade_date", "provider_source", "source_type", "margin_balance_5d_flat_or_down", "hot_stock_margin_fast_increase", "margin_balance_5d_increases", "index_5d_return_pct", "margin_balance_5d_decline_pct", "margin_not_retreating"),
        ("index_5d_return_pct", "margin_balance_5d_decline_pct"),
        ("margin_balance_5d_flat_or_down", "hot_stock_margin_fast_increase", "margin_balance_5d_increases", "margin_not_retreating"),
    ),
)

SCHEMAS_BY_FILE = {schema.filename: schema for schema in SCHEMAS}


def validate_daily_input_csvs(*, trade_date: date, input_dir: str | Path) -> list[str]:
    """Return validation errors for one local daily input directory."""

    root = Path(input_dir)
    errors: list[str] = []
    errors.extend(_forbidden_bcd_artifact_errors(root))
    for schema in SCHEMAS:
        path = root / schema.filename
        if not path.exists():
            errors.append(f"missing required CSV: {path}")
            continue
        try:
            with path.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                fieldnames = list(reader.fieldnames or [])
                rows = list(reader)
        except OSError as exc:
            errors.append(f"{schema.filename}: cannot read CSV: {exc}")
            continue
        forbidden_columns = _forbidden_bcd_columns(fieldnames)
        if forbidden_columns:
            errors.append(f"{schema.filename}: forbidden provider BCD column(s): {', '.join(forbidden_columns)}. {PROVIDER_BCD_FORBIDDEN_MESSAGE}")
        if not rows:
            errors.append(f"{schema.filename}: row count must be > 0")
        missing = [column for column in schema.required_columns if column not in fieldnames]
        if missing:
            errors.append(f"{schema.filename}: missing required columns: {', '.join(missing)}")
        for index, row in enumerate(rows, start=2):
            row_date = (row.get("trade_date") or "").strip()
            if row_date != trade_date.isoformat():
                errors.append(f"{schema.filename}: line {index}: trade_date {row_date!r} does not match {trade_date.isoformat()}")
            provider_source = (row.get("provider_source") or "").strip()
            if not provider_source:
                errors.append(f"{schema.filename}: line {index}: provider_source is required")
            source_type = (row.get("source_type") or "").strip().lower()
            if not source_type:
                errors.append(f"{schema.filename}: line {index}: source_type is required")
            elif source_type in FORBIDDEN_SOURCE_TYPES:
                errors.append(f"{schema.filename}: line {index}: forbidden source_type {source_type!r}")
            for column in schema.numeric_columns:
                value = (row.get(column) or "").strip().replace(",", "")
                if value == "":
                    errors.append(f"{schema.filename}: line {index}: numeric field {column} is blank")
                    continue
                try:
                    float(value)
                except ValueError:
                    errors.append(f"{schema.filename}: line {index}: numeric field {column} is not parseable: {row.get(column)!r}")
            for column in schema.bool_columns:
                value = (row.get(column) or "").strip().lower()
                if value not in {"true", "false", "1", "0", "yes", "no", "y", "n"}:
                    errors.append(f"{schema.filename}: line {index}: boolean field {column} is not parseable: {row.get(column)!r}")
    return errors



def _forbidden_bcd_columns(fieldnames: Sequence[str] | None) -> list[str]:
    return [name for name in (fieldnames or ()) if str(name).strip() in FORBIDDEN_PROVIDER_BCD_FIELDS]


def _forbidden_bcd_artifact_errors(root: Path) -> list[str]:
    errors: list[str] = []
    if not root.exists():
        return errors
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in SCHEMAS_BY_FILE:
            continue
        suffix = path.suffix.lower()
        if suffix == ".csv":
            try:
                with path.open(newline="", encoding="utf-8-sig") as handle:
                    columns = _forbidden_bcd_columns(csv.DictReader(handle).fieldnames)
            except OSError as exc:
                errors.append(f"{path.relative_to(root)}: cannot read provider artifact: {exc}")
                continue
            if columns:
                errors.append(f"{path.relative_to(root)}: forbidden provider BCD column(s): {', '.join(columns)}. {PROVIDER_BCD_FORBIDDEN_MESSAGE}")
        elif suffix == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"{path.relative_to(root)}: cannot read provider artifact JSON: {exc}")
                continue
            locations = _forbidden_bcd_json_locations(payload)
            if locations:
                errors.append(f"{path.relative_to(root)}: forbidden provider BCD field(s) at {', '.join(locations)}. {PROVIDER_BCD_FORBIDDEN_MESSAGE}")
    return errors


def _forbidden_bcd_json_locations(value: Any, prefix: str = "$") -> list[str]:
    locations: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}"
            if str(key) in FORBIDDEN_PROVIDER_BCD_FIELDS:
                locations.append(child_prefix)
            locations.extend(_forbidden_bcd_json_locations(child, child_prefix))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            locations.extend(_forbidden_bcd_json_locations(child, f"{prefix}[{index}]"))
    return locations

def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the eight required local daily TDT-RM input CSV files.")
    parser.add_argument("--trade-date", required=True, type=date.fromisoformat, help="Target trade date, YYYY-MM-DD.")
    parser.add_argument("--input-dir", required=True, help="Directory containing the eight daily input CSV files.")
    args = parser.parse_args()

    errors = validate_daily_input_csvs(trade_date=args.trade_date, input_dir=args.input_dir)
    if errors:
        print("Daily input CSV validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Daily input CSV validation passed for {args.trade_date.isoformat()} in {args.input_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
