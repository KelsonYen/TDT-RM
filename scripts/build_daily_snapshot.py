#!/usr/bin/env python
"""Build a normalized TDT-RM daily market snapshot from local CSV/JSON input."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tdt_rm.daily_snapshot import (
    load_daily_snapshot_csv,
    load_daily_snapshot_json,
    validate_daily_snapshot,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a normalized TDT-RM daily market snapshot JSON.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input-csv", help="One-row local CSV containing canonical or mapped market fields.")
    source.add_argument("--input-json", help="Existing daily snapshot JSON or JSON object with canonical_row.")
    parser.add_argument("--field-map", help="Optional JSON mapping of canonical field names to CSV header names.")
    parser.add_argument("--output-json", required=True, help="Output path for normalized daily snapshot JSON.")
    parser.add_argument("--as-of", type=date.fromisoformat, help="Optional YYYY-MM-DD validation as-of date.")
    parser.add_argument("--validate", action="store_true", help="Validate the snapshot and exit non-zero on blocking errors.")
    args = parser.parse_args()

    field_map = None
    if args.field_map:
        field_map = json.loads(Path(args.field_map).read_text(encoding="utf-8"))
        if not isinstance(field_map, dict):
            raise SystemExit("--field-map must be a JSON object")

    snapshot = (
        load_daily_snapshot_csv(args.input_csv, field_map=field_map)
        if args.input_csv
        else load_daily_snapshot_json(args.input_json)
    )
    validation = validate_daily_snapshot(snapshot, as_of=args.as_of)
    output_payload = snapshot.as_dict()
    output_payload["validation"] = validation.as_dict()
    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Snapshot: {output_path}")
    print(f"Validation: {'passed' if validation.is_valid else 'failed'}")
    if args.validate and not validation.is_valid:
        for issue in validation.issues:
            if issue.severity == "error":
                print(f"ERROR {issue.code}: {issue.message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
