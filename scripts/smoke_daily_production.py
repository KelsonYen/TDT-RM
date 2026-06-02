#!/usr/bin/env python
"""Run an end-to-end TDT-RM enriched daily snapshot smoke test."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tdt_rm.daily_runner import DEFAULT_OUTPUT_DIR, run_daily_production
from tdt_rm.daily_validation import validate_daily_artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test enriched snapshot daily production artifacts.")
    parser.add_argument("--snapshot-path", required=True, help="Normalized daily snapshot JSON path.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for smoke-test JSON, Markdown, and manifest artifacts.",
    )
    parser.add_argument("--as-of", type=date.fromisoformat, help="Optional YYYY-MM-DD validation as-of date.")
    args = parser.parse_args()

    result = run_daily_production(
        as_of=args.as_of,
        output_dir=args.output_dir,
        write_manifest=True,
        command="scripts/smoke_daily_production.py",
        snapshot_path=args.snapshot_path,
    )
    manifest_path = result.manifest_path
    if manifest_path is None:
        raise RuntimeError("smoke run did not produce a manifest")

    missing = [path for path in (result.json_path, result.markdown_path, manifest_path) if not path.exists()]
    if missing:
        for path in missing:
            print(f"ERROR missing artifact: {path}", file=sys.stderr)
        return 1

    validation = validate_daily_artifacts(result.json_path, result.markdown_path, as_of=args.as_of)
    payload = dict(result.payload)
    data = _mapping(payload.get("data"))
    scores = _mapping(payload.get("scores"))

    print("TDT-RM daily production smoke summary")
    print(f"trade_date: {payload.get('trade_date')}")
    print(f"signal: {payload.get('signal')}")
    print(f"exposure_limit: {payload.get('equity_exposure_limit')}")
    print(f"TCWRS: {scores.get('TCWRS')}")
    print(f"ETI-5: {scores.get('ETI-5')}")
    print(f"Tail Risk: {scores.get('Tail Risk')}")
    print(f"BCD: {scores.get('BCD')}")
    print(f"CP: {scores.get('CP')}")
    print(f"data_status: {data.get('status') or data.get('data_status')}")
    print(f"fallback_proxies: {json.dumps(data.get('fallback_proxies', {}), ensure_ascii=False, sort_keys=True)}")
    print(f"validation_status: {validation.status}")
    print(f"json_path: {result.json_path}")
    print(f"markdown_path: {result.markdown_path}")
    print(f"manifest_path: {manifest_path}")

    if validation.has_errors:
        for issue in validation.errors:
            print(f"ERROR {issue.code}: {issue.message}", file=sys.stderr)
        return 1
    return 0


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


if __name__ == "__main__":
    raise SystemExit(main())
