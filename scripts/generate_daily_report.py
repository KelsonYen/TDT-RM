#!/usr/bin/env python
"""Generate an operator-facing daily production audit report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a TDT-RM daily report from production artifacts.")
    parser.add_argument("--fetch-manifest", required=True, help="Path to fetch_manifest.json.")
    parser.add_argument("--pipeline-summary", help="Optional combined/pipeline summary JSON.")
    parser.add_argument("--output", required=True, help="Markdown report output path.")
    args = parser.parse_args()

    try:
        manifest = _load_json(Path(args.fetch_manifest))
        pipeline = _load_json(Path(args.pipeline_summary)) if args.pipeline_summary else None
        report = render_daily_report(manifest, pipeline)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - concise CLI error.
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    print(str(args.output))
    return 0


def render_daily_report(fetch_manifest: Mapping[str, Any], pipeline_summary: Mapping[str, Any] | None = None) -> str:
    as_of = fetch_manifest.get("as_of", "unknown")
    provider_health = fetch_manifest.get("provider_health") if isinstance(fetch_manifest.get("provider_health"), Mapping) else {}
    source_attempts = fetch_manifest.get("source_attempts") if isinstance(fetch_manifest.get("source_attempts"), list) else []
    limitations = fetch_manifest.get("limitations") if isinstance(fetch_manifest.get("limitations"), list) else []
    pipeline = _pipeline_payload(pipeline_summary)
    validation = pipeline.get("validation") if isinstance(pipeline.get("validation"), Mapping) else {}

    lines = [
        f"# TDT-RM Daily Production Audit — {as_of}",
        "",
        "## Executive Summary",
        f"- Fetch data status: `{fetch_manifest.get('data_status')}`",
        f"- Successful sources: {_csv(fetch_manifest.get('successful_sources'))}",
        f"- Failed/stale/unavailable sources: {_csv((fetch_manifest.get('failed_sources') or []) + (fetch_manifest.get('stale_sources') or []) + (fetch_manifest.get('unavailable_sources') or []))}",
    ]
    if pipeline:
        lines.extend(
            [
                f"- Signal: `{pipeline.get('signal')}`",
                f"- Exposure limit: `{pipeline.get('exposure_limit')}`",
                f"- Validation status: `{pipeline.get('validation_status') or validation.get('status')}`",
            ]
        )
    lines.extend(["", "## Provider Health", "", "| Provider | Status | Source Type | Records | Freshness | Decision |", "| --- | --- | --- | ---: | --- | --- |"])
    for name in sorted(str(key) for key in provider_health):
        item = provider_health.get(name)
        if not isinstance(item, Mapping):
            continue
        diagnostics = item.get("diagnostics") if isinstance(item.get("diagnostics"), Mapping) else {}
        lines.append(
            "| "
            + " | ".join(
                [
                    name,
                    str(item.get("status")),
                    str(item.get("source_type")),
                    str(item.get("records_loaded")),
                    str(item.get("freshness_status")),
                    str(diagnostics.get("final_decision") if isinstance(diagnostics, Mapping) else ""),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Source Attempts", "", "| Source | Category | Status | Cache | Failure Reason | Fields |", "| --- | --- | --- | --- | --- | --- |"])
    for attempt in source_attempts:
        if not isinstance(attempt, Mapping):
            continue
        cache = "hit" if _attempt_cache_hit(attempt) else "-"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(attempt.get("source_id")),
                    str(attempt.get("provider_category")),
                    str(attempt.get("status")),
                    cache,
                    _escape(str(attempt.get("failure_reason") or "")),
                    _escape(", ".join(str(field) for field in attempt.get("fields_extracted", []) or [])),
                ]
            )
            + " |"
        )
    if pipeline:
        scores = pipeline.get("scores") if isinstance(pipeline.get("scores"), Mapping) else {}
        lines.extend(["", "## Daily Signal", ""])
        for key in ("TCWRS", "MHS", "ETI-5", "Tail Risk", "BCD", "CP"):
            lines.append(f"- {key}: `{scores.get(key)}`")
        lines.append(f"- Available ETI components: {_csv(pipeline.get('available_eti_components'))}")
        lines.append(f"- Fallback proxies: `{json.dumps(pipeline.get('fallback_proxies', {}), ensure_ascii=False, sort_keys=True)}`")
        artifacts = pipeline.get("artifact_paths") if isinstance(pipeline.get("artifact_paths"), Mapping) else {}
        lines.extend(["", "## Artifacts", ""])
        for key in sorted(artifacts):
            lines.append(f"- {key}: `{artifacts[key]}`")
    lines.extend(["", "## Limitations", ""])
    if limitations:
        lines.extend(f"- {item}" for item in limitations)
    else:
        lines.append("- None recorded.")
    lines.append("")
    return "\n".join(lines)


def _load_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _pipeline_payload(summary: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(summary, Mapping):
        return {}
    value = summary.get("pipeline")
    return value if isinstance(value, Mapping) else summary


def _csv(value: Any) -> str:
    if isinstance(value, list | tuple):
        return ", ".join(str(item) for item in value) or "none"
    return str(value) if value else "none"


def _escape(value: str) -> str:
    return value.replace("|", "\\|")


def _attempt_cache_hit(attempt: Mapping[str, Any]) -> bool:
    cache = attempt.get("cache")
    return isinstance(cache, Mapping) and bool(cache.get("hit"))


if __name__ == "__main__":
    raise SystemExit(main())
