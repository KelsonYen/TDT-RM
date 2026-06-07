#!/usr/bin/env python
"""Trace a daily field through production artifacts for one trade date."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Trace one field through daily production artifacts.")
    parser.add_argument("--trade-date", required=True, help="Trade date YYYY-MM-DD.")
    parser.add_argument("--field", required=True, help="Field to trace, e.g. main7_closes or bcd.")
    args = parser.parse_args()

    trade_date = args.trade_date
    field = args.field
    stages = _stages(trade_date, field)
    print(f"lineage trace trade_date={trade_date} field={field}")
    for stage in stages:
        value = stage["value"]
        exists = stage["exists"]
        preview = _preview(value)
        path = stage.get("path") or "n/a"
        source = stage.get("source") or "n/a"
        print(f"{stage['stage']}: {'FOUND' if exists else 'MISSING'} | path={path} | source={source} | value={preview}")
    return 0


def _stages(trade_date: str, field: str) -> list[dict[str, Any]]:
    input_dir = ROOT / "inputs" / "daily" / trade_date
    strict_dir = input_dir / "_strict_provider_csvs"
    artifacts = ROOT / "reports" / "daily" / trade_date / "artifacts"
    outputs = ROOT / "outputs" / "daily" / f"{trade_date}-rerun"
    bcd_keys = {"bcd", "BCD"}
    if field in bcd_keys:
        return [
            _json_stage("Provider fetch summary", artifacts / "production_fetch_summary.json", ("datasets", "leadership")),
            _json_stage("Snapshot assembly", artifacts / f"assembled_daily_snapshot_{trade_date}.json", ("canonical_row", "bcd")),
            _json_stage("BCD audit payload", artifacts / "bcd_audit_trace.json", ("final_score",)),
            _json_stage("Daily JSON score", artifacts / f"tdt_rm_daily_{trade_date}.json", ("bcd",)),
            _json_stage("Daily JSON status", artifacts / f"tdt_rm_daily_{trade_date}.json", ("bcd_status",)),
            _markdown_stage("User report", artifacts / f"tdt_rm_daily_{trade_date}.md", "BCD"),
            _directory_stage("Legacy rerun outputs", outputs),
        ]
    return [
        _json_stage("Provider raw row", strict_dir / "_raw" / "leadership" / "TWSE_OFFICIAL.json", ("row", field)),
        _csv_stage("Fetcher/parser strict leadership.csv", strict_dir / "leadership.csv", field),
        _csv_stage("Production leadership.csv", input_dir / "leadership.csv", field),
        _json_stage("Snapshot assembly", artifacts / f"assembled_daily_snapshot_{trade_date}.json", ("canonical_row", field)),
        _json_stage("BCD enrichment final fields", artifacts / "bcd_feature_enrichment_trace.json", ("final_fields_passed_to_BCDInput", field)),
        _json_stage("BCDInput raw_inputs", artifacts / "bcd_audit_trace.json", ("raw_inputs", field)),
        _json_stage("BCD source_fields", artifacts / "bcd_audit_trace.json", ("source_fields", field)),
        _json_stage("Final BCD audit payload", artifacts / f"tdt_rm_daily_{trade_date}.json", ("traces", "bcd", "raw_inputs", field)),
        _directory_stage("Legacy rerun outputs", outputs),
    ]


def _csv_stage(stage: str, path: Path, field: str) -> dict[str, Any]:
    if not path.exists():
        return {"stage": stage, "path": str(path), "exists": False, "value": None, "source": "file_missing"}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        row = next(reader, {})
        has_column = field in (reader.fieldnames or [])
    return {"stage": stage, "path": str(path), "exists": bool(has_column and row.get(field) not in {None, ""}), "value": row.get(field) if has_column else None, "source": "csv_column" if has_column else "column_missing"}


def _json_stage(stage: str, path: Path, keys: tuple[str, ...]) -> dict[str, Any]:
    if not path.exists():
        return {"stage": stage, "path": str(path), "exists": False, "value": None, "source": "file_missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"stage": stage, "path": str(path), "exists": False, "value": None, "source": f"json_error:{exc}"}
    value: Any = payload
    for key in keys:
        if isinstance(value, Mapping) and key in value:
            value = value[key]
        else:
            return {"stage": stage, "path": str(path), "exists": False, "value": None, "source": ".".join(keys)}
    return {"stage": stage, "path": str(path), "exists": _exists_value(value), "value": value, "source": ".".join(keys)}


def _markdown_stage(stage: str, path: Path, needle: str) -> dict[str, Any]:
    if not path.exists():
        return {"stage": stage, "path": str(path), "exists": False, "value": None, "source": "file_missing"}
    for line in path.read_text(encoding="utf-8").splitlines():
        if needle in line:
            return {"stage": stage, "path": str(path), "exists": True, "value": line, "source": "matching_line"}
    return {"stage": stage, "path": str(path), "exists": False, "value": None, "source": "matching_line_missing"}


def _directory_stage(stage: str, path: Path) -> dict[str, Any]:
    files = sorted(str(item.relative_to(path)) for item in path.rglob("*") if item.is_file()) if path.exists() else []
    return {"stage": stage, "path": str(path), "exists": bool(files), "value": files[:10], "source": "directory_listing"}


def _exists_value(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, (dict, list, tuple)):
        return bool(value)
    return True


def _preview(value: Any, limit: int = 240) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list, tuple)) else str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


if __name__ == "__main__":
    raise SystemExit(main())
