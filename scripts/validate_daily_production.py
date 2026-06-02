#!/usr/bin/env python
"""Validate TDT-RM daily production JSON/Markdown artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tdt_rm.daily_validation import build_daily_run_manifest, validate_daily_artifacts, validate_daily_payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate TDT-RM daily production artifacts.")
    parser.add_argument("--json-path", required=True, help="Path to tdt_rm_daily_YYYY-MM-DD.json.")
    parser.add_argument("--markdown-path", required=True, help="Path to tdt_rm_daily_YYYY-MM-DD.md.")
    parser.add_argument("--as-of", type=date.fromisoformat, help="Optional as-of date for stale-data checks (YYYY-MM-DD).")
    parser.add_argument("--manifest-out", help="Optional path to write a validation run manifest JSON.")
    args = parser.parse_args()

    result = validate_daily_artifacts(args.json_path, args.markdown_path)
    payload = None
    json_path = Path(args.json_path)
    if json_path.exists():
        try:
            loaded = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
                if args.as_of is not None:
                    result = validate_daily_payload(payload, as_of=args.as_of)
                    # Preserve companion Markdown checks when as_of is requested.
                    artifact_result = validate_daily_artifacts(args.json_path, args.markdown_path)
                    result = type(result)(tuple(result.issues + artifact_result.issues))
        except json.JSONDecodeError:
            payload = None

    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))

    if args.manifest_out:
        if payload is None:
            payload = {}
        manifest = build_daily_run_manifest(
            payload,
            args.json_path,
            args.markdown_path,
            command="scripts/validate_daily_production.py",
            validation=result,
        )
        Path(args.manifest_out).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    return 1 if result.has_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
