#!/usr/bin/env python
"""Render a GitHub Actions summary for production connectivity/fetch runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

DATASETS = ("price", "foreign_flow", "fx", "breadth", "futures", "options", "leadership", "margin")


def main() -> int:
    parser = argparse.ArgumentParser(description="Render production fetch connectivity summary Markdown.")
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--reports-dir", required=True)
    parser.add_argument("--connectivity-audit-dir", default="")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    reports_dir = Path(args.reports_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir = reports_dir / "artifacts"
    manifest = _load_json(output_dir / "fetch_manifest.json")
    fetch_summary = _load_json(artifact_dir / "production_fetch_summary.json")
    provider_health = _load_json(artifact_dir / "provider_health.json")
    validation = _load_json(artifact_dir / "validation_report.json")
    connectivity = _load_json(Path(args.connectivity_audit_dir) / "connectivity_audit.json") if args.connectivity_audit_dir else {}

    payload = {
        "trade_date": args.trade_date,
        "manifest_status": manifest.get("data_status", "missing"),
        "production_ready": bool(manifest.get("production_ready")),
        "failure_classes": _failure_class_counts(manifest.get("source_attempts")),
        "artifacts": {
            "provider_connectivity_summary": str(output_dir / "provider_connectivity_summary.json"),
            "fetch_manifest": str(output_dir / "fetch_manifest.json"),
            "production_fetch_summary": str(artifact_dir / "production_fetch_summary.json"),
            "provider_csvs": str(input_dir / "_strict_provider_csvs"),
        },
    }
    (output_dir / "provider_connectivity_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(_render_markdown(args.trade_date, input_dir, output_dir, reports_dir, manifest, fetch_summary, provider_health, validation, connectivity))
    return 0


def _render_markdown(
    trade_date: str,
    input_dir: Path,
    output_dir: Path,
    reports_dir: Path,
    manifest: Mapping[str, Any],
    fetch_summary: Mapping[str, Any],
    provider_health: Mapping[str, Any],
    validation: Mapping[str, Any],
    connectivity: Mapping[str, Any],
) -> str:
    lines = [
        "## Production connectivity and fetch validation",
        "",
        f"- trade_date: `{trade_date}`",
        f"- data_status: `{manifest.get('data_status', 'missing')}`",
        f"- production_ready: `{bool(manifest.get('production_ready'))}`",
        f"- pipeline_status: `{manifest.get('pipeline_status', 'missing')}`",
        f"- validation_status: `{_validation_status(validation)}`",
        f"- FinMind live enabled: `{bool(manifest.get('finmind_live_enabled'))}`",
        f"- blocking_error: `{manifest.get('blocking_error') or 'none'}`",
        "",
        "### Provider attempts",
        "| Dataset | Provider | Endpoint attempted | HTTP status / exception | Rows fetched | Parser status | Validation status | Failure class |",
        "| --- | --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for attempt in _attempt_rows(manifest, provider_health):
        lines.append(
            "| "
            f"`{_cell(attempt.get('provider_category'))}` | "
            f"`{_cell(attempt.get('source_id'))}` | "
            f"{_code_cell(attempt.get('endpoint_attempted'))} | "
            f"{_status_cell(attempt)} | "
            f"{int(attempt.get('rows_fetched') or 0)} | "
            f"`{_cell(attempt.get('parser_status'))}` | "
            f"`{_cell(attempt.get('validation_status'))}` | "
            f"`{_cell(attempt.get('failure_class'))}` |"
        )
    if not _attempt_rows(manifest, provider_health):
        lines.append("| `none` | `none` | `not captured` | `not captured` | 0 | `not_reached` | `not_reached` | `unknown` |")

    lines.extend([
        "",
        "### Dataset readiness",
        "| Dataset | Provider CSV | Rows | Status |",
        "| --- | --- | ---: | --- |",
    ])
    provider_paths = manifest.get("provider_csv_paths") if isinstance(manifest.get("provider_csv_paths"), Mapping) else {}
    missing = set(str(item) for item in manifest.get("missing_production_csvs", []) if isinstance(manifest.get("missing_production_csvs"), list))
    for dataset in DATASETS:
        path = Path(str(provider_paths.get(dataset) or input_dir / "_strict_provider_csvs" / f"{dataset}.csv"))
        rows = _csv_row_count(path)
        status = "written" if path.exists() and dataset not in missing else "missing"
        lines.append(f"| `{dataset}` | `{path}` | {rows} | `{status}` |")

    if connectivity:
        summary = connectivity.get("summary") if isinstance(connectivity.get("summary"), Mapping) else {}
        lines.extend([
            "",
            "### Lightweight provider connectivity audit",
            f"- Runtime context: `{connectivity.get('runtime_context', 'unknown')}`",
            f"- Usable providers: `{summary.get('usable_providers', 'unknown')}`",
            f"- Blocked providers: `{summary.get('blocked_providers', 'unknown')}`",
        ])

    lines.extend([
        "",
        "### Uploaded artifact paths",
        f"- Provider connectivity summary: `{output_dir / 'provider_connectivity_summary.json'}`",
        f"- Fetch manifest: `{output_dir / 'fetch_manifest.json'}`",
        f"- Production fetch summary: `{reports_dir / 'artifacts' / 'production_fetch_summary.json'}`",
        f"- Provider CSVs: `{input_dir / '_strict_provider_csvs'}`",
        f"- Production inputs: `{input_dir}`",
    ])
    return "\n".join(lines) + "\n"


def _attempt_rows(manifest: Mapping[str, Any], provider_health: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    attempts = manifest.get("source_attempts")
    if isinstance(attempts, list) and attempts:
        return [attempt for attempt in attempts if isinstance(attempt, Mapping)]
    rows: list[Mapping[str, Any]] = []
    providers = provider_health.get("providers")
    if isinstance(providers, Mapping):
        for entry in providers.values():
            if isinstance(entry, Mapping):
                dataset = str(entry.get("dataset") or "")
                for attempt in entry.get("attempts", []) if isinstance(entry.get("attempts"), list) else []:
                    if isinstance(attempt, Mapping):
                        rows.append({"provider_category": dataset, "source_id": attempt.get("provider"), "success": attempt.get("status") == "healthy"})
    return rows


def _failure_class_counts(attempts: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for attempt in attempts if isinstance(attempts, list) else []:
        if isinstance(attempt, Mapping):
            key = str(attempt.get("failure_class") or "unknown")
            counts[key] = counts.get(key, 0) + 1
    return counts


def _validation_status(validation: Mapping[str, Any]) -> str:
    return str(validation.get("overall_status") or "not_reached")


def _status_cell(attempt: Mapping[str, Any]) -> str:
    status = attempt.get("http_status")
    if status:
        return f"`HTTP {status}`"
    exception = attempt.get("network_exception") or attempt.get("error")
    return _code_cell(exception or "none")


def _code_cell(value: object) -> str:
    text = _cell(value)
    if len(text) > 96:
        text = text[:93] + "..."
    return f"`{text}`"


def _cell(value: object) -> str:
    return str(value if value not in {None, ""} else "n/a").replace("|", "\\|").replace("\n", " ")


def _csv_row_count(path: Path) -> int:
    try:
        import csv

        with path.open(newline="", encoding="utf-8-sig") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    except OSError:
        return 0


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
