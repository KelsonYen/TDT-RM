#!/usr/bin/env python
"""Render a concise provider health summary for daily operations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render TDT-RM provider health diagnostics.")
    parser.add_argument("--health-json", required=True, help="Path to provider_health.json.")
    args = parser.parse_args(argv)

    try:
        health = _load_health(Path(args.health_json))
        print(render_provider_health_report(health))
    except Exception as exc:  # noqa: BLE001 - concise CLI error.
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    return 0


def _load_health(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"provider health JSON not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("provider health JSON root must be an object")
    providers = payload.get("providers")
    if not isinstance(providers, Mapping) or not providers:
        raise ValueError("provider health JSON must contain a non-empty providers object")
    return payload


def render_provider_health_report(health: Mapping[str, Any]) -> str:
    providers = health.get("providers")
    if not isinstance(providers, Mapping) or not providers:
        raise ValueError("provider health JSON must contain a non-empty providers object")

    lines = ["Provider Health Summary", ""]
    for provider_name in sorted(str(key) for key in providers):
        raw = providers[provider_name]
        if not isinstance(raw, Mapping):
            continue
        diagnostics = raw.get("diagnostics") if isinstance(raw.get("diagnostics"), Mapping) else {}
        messages = []
        if isinstance(diagnostics, Mapping):
            raw_messages = diagnostics.get("messages")
            if isinstance(raw_messages, list):
                messages.extend(str(item) for item in raw_messages if str(item))
        error_message = str(raw.get("error_message") or "")
        if error_message:
            messages.append(error_message)

        lines.extend(
            [
                f"{provider_name}: {raw.get('status')}",
                f"as_of: {raw.get('as_of')}",
                f"source_type: {raw.get('source_type')}",
                f"records_loaded: {raw.get('records_loaded')}",
            ]
        )
        if messages:
            lines.append("diagnostics: " + "; ".join(dict.fromkeys(messages)))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
