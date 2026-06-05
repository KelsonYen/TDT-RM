#!/usr/bin/env python
"""Render a GitHub Actions summary for production connectivity/fetch runs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

DATASETS = ("price", "foreign_flow", "fx", "breadth", "futures", "options", "leadership", "margin")
AUDIT_DATASETS = ("price", "foreign_flow", "fx", "breadth", "futures", "options", "leadership")


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

    audit_matrix = _dataset_audit_matrix(args.trade_date, input_dir, manifest, fetch_summary, provider_health)
    _write_augmented_fetch_summary(artifact_dir / "production_fetch_summary.json", args.trade_date, manifest, fetch_summary, audit_matrix)

    payload = {
        "trade_date": args.trade_date,
        "as_of": args.trade_date,
        "run_id": _env("GITHUB_RUN_ID"),
        "commit_sha": _env("GITHUB_SHA"),
        "artifact_name": _artifact_name(args.trade_date),
        "artifact_digest": _env("TDT_RM_ARTIFACT_DIGEST", "not available before upload"),
        "manifest_status": manifest.get("data_status", "missing"),
        "production_ready": bool(manifest.get("production_ready")),
        "missing_datasets": _missing_dataset_names(manifest),
        "failure_classes": _failure_class_counts(manifest.get("source_attempts")),
        "dataset_audit_matrix": audit_matrix,
        "artifacts": {
            "provider_connectivity_summary": str(output_dir / "provider_connectivity_summary.json"),
            "fetch_manifest": str(output_dir / "fetch_manifest.json"),
            "production_fetch_summary": str(artifact_dir / "production_fetch_summary.json"),
            "provider_health": str(artifact_dir / "provider_health.json"),
            "provider_csvs": str(input_dir / "_strict_provider_csvs"),
        },
    }
    (output_dir / "provider_connectivity_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(_render_markdown(args.trade_date, input_dir, output_dir, reports_dir, manifest, fetch_summary, provider_health, validation, connectivity, audit_matrix))
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
    audit_matrix: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    matrix = list(audit_matrix) if audit_matrix is not None else _dataset_audit_matrix(trade_date, input_dir, manifest, fetch_summary, provider_health)
    lines = [
        "## Production connectivity and fetch validation",
        "",
        f"- run id: `{_env('GITHUB_RUN_ID')}`",
        f"- commit sha: `{_env('GITHUB_SHA')}`",
        f"- trade_date: `{trade_date}`",
        f"- as_of date: `{manifest.get('as_of') or trade_date}`",
        f"- artifact name: `{_artifact_name(trade_date)}`",
        f"- artifact digest: `{_env('TDT_RM_ARTIFACT_DIGEST', 'not available before upload')}`",
        f"- data_status: `{manifest.get('data_status', 'missing')}`",
        f"- production_ready: `{bool(manifest.get('production_ready'))}`",
        f"- missing datasets: `{', '.join(_missing_dataset_names(manifest)) or 'none'}`",
        f"- pipeline_status: `{manifest.get('pipeline_status', 'missing')}`",
        f"- validation_status: `{_validation_status(validation)}`",
        f"- FinMind live enabled: `{bool(manifest.get('finmind_live_enabled'))}`",
        f"- blocking_error: `{manifest.get('blocking_error') or 'none'}`",
        "",
        "### Provider attempts",
        "| Dataset | Provider | Endpoint attempted | HTTP status / exception | Rows fetched | Parser status | Validation status | Failure class | Failure layer |",
        "| --- | --- | --- | --- | ---: | --- | --- | --- | --- |",
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
            f"`{_cell(attempt.get('failure_class'))}` | "
            f"`{_cell(attempt.get('failure_layer'))}` |"
        )
    if not _attempt_rows(manifest, provider_health):
        lines.append("| `none` | `none` | `not captured` | `not captured` | 0 | `not_reached` | `not_reached` | `unknown` | `UNKNOWN` |")

    lines.extend([
        "",
        "### Required dataset audit matrix",
        "| Dataset | Provider chain | Provider attempted | Exact URL or endpoint domain attempted | Exact exception message | HTTP status | Failure happened at | Parser executed? | Validation executed? | Output CSV written? | Root cause classification |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for row in matrix:
        lines.append(
            "| "
            f"`{_cell(row.get('dataset'))}` | "
            f"{_code_cell(row.get('provider_chain'))} | "
            f"{_code_cell(row.get('provider_attempted'))} | "
            f"{_code_cell(row.get('endpoint_attempted'))} | "
            f"{_code_cell(row.get('exception_message'))} | "
            f"{_code_cell(row.get('http_status'))} | "
            f"`{_cell(row.get('failure_happened_at'))}` | "
            f"`{_cell(row.get('parser_executed'))}` | "
            f"`{_cell(row.get('validation_executed'))}` | "
            f"`{_cell(row.get('output_csv_written'))}` | "
            f"`{_cell(row.get('root_cause_classification'))}` |"
        )

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


def _dataset_audit_matrix(
    trade_date: str,
    input_dir: Path,
    manifest: Mapping[str, Any],
    fetch_summary: Mapping[str, Any],
    provider_health: Mapping[str, Any],
) -> list[dict[str, Any]]:
    attempts = _attempt_rows(manifest, provider_health)
    attempts_by_dataset: dict[str, list[Mapping[str, Any]]] = {dataset: [] for dataset in AUDIT_DATASETS}
    for attempt in attempts:
        dataset = str(attempt.get("provider_category") or attempt.get("dataset") or "")
        if dataset in attempts_by_dataset:
            attempts_by_dataset[dataset].append(attempt)
    provider_paths = manifest.get("provider_csv_paths") if isinstance(manifest.get("provider_csv_paths"), Mapping) else {}
    missing = set(_missing_dataset_names(manifest))
    summary_datasets = fetch_summary.get("datasets") if isinstance(fetch_summary.get("datasets"), Mapping) else {}
    rows: list[dict[str, Any]] = []
    for dataset in AUDIT_DATASETS:
        dataset_attempts = attempts_by_dataset.get(dataset, [])
        summary_row = summary_datasets.get(dataset) if isinstance(summary_datasets.get(dataset), Mapping) else {}
        selected = _selected_or_last_attempt(dataset_attempts)
        chain = _provider_chain(dataset_attempts, summary_row)
        output_path = Path(str(provider_paths.get(dataset) or input_dir / "_strict_provider_csvs" / f"{dataset}.csv"))
        output_written = output_path.exists() and dataset not in missing
        parser_status = _combined_status(dataset_attempts, "parser_status", selected.get("parser_status"))
        validation_status = _combined_status(dataset_attempts, "validation_status", selected.get("validation_status"))
        http_statuses = _joined_unique(_normal_status(attempt.get("http_status")) for attempt in dataset_attempts if _normal_status(attempt.get("http_status")) != "n/a")
        exception_messages = _joined_unique(_attempt_error(attempt) for attempt in dataset_attempts if _attempt_error(attempt) != "n/a")
        endpoints = _joined_unique(_cell(attempt.get("endpoint_attempted")) for attempt in dataset_attempts if _cell(attempt.get("endpoint_attempted")) != "n/a")
        root_cause = _root_cause(dataset_attempts, selected, output_written)
        rows.append(
            {
                "dataset": dataset,
                "provider_chain": chain,
                "provider_attempted": _joined_unique(_cell(attempt.get("source_id") or attempt.get("provider_id") or attempt.get("provider")) for attempt in dataset_attempts) or _cell(summary_row.get("provider_used")),
                "endpoint_attempted": endpoints or "not captured",
                "exception_message": exception_messages or "none" if output_written else exception_messages or str(manifest.get("blocking_error") or "not captured"),
                "http_status": http_statuses or "n/a",
                "failure_happened_at": _failure_stage(selected, parser_status, validation_status, output_written),
                "parser_executed": _executed(parser_status),
                "validation_executed": _executed(validation_status),
                "output_csv_written": "YES" if output_written else "NO",
                "root_cause_classification": root_cause,
            }
        )
    return rows


def _write_augmented_fetch_summary(path: Path, trade_date: str, manifest: Mapping[str, Any], fetch_summary: Mapping[str, Any], audit_matrix: Sequence[Mapping[str, Any]]) -> None:
    payload = dict(fetch_summary) if isinstance(fetch_summary, Mapping) else {}
    payload.setdefault("trade_date", trade_date)
    payload.setdefault("as_of", trade_date)
    payload["run_id"] = _env("GITHUB_RUN_ID")
    payload["commit_sha"] = _env("GITHUB_SHA")
    payload["artifact_name"] = _artifact_name(trade_date)
    payload["artifact_digest"] = _env("TDT_RM_ARTIFACT_DIGEST", "not available before upload")
    payload["production_ready"] = bool(manifest.get("production_ready"))
    payload["missing_datasets"] = _missing_dataset_names(manifest) or payload.get("missing_datasets", [])
    payload["dataset_audit_matrix"] = list(audit_matrix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _selected_or_last_attempt(attempts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    for attempt in attempts:
        if attempt.get("selected") or attempt.get("success"):
            return attempt
    return attempts[-1] if attempts else {}


def _provider_chain(attempts: Sequence[Mapping[str, Any]], summary_row: Mapping[str, Any]) -> str:
    chain = _joined_unique(_cell(attempt.get("source_id") or attempt.get("provider_id") or attempt.get("provider")) for attempt in attempts)
    if chain:
        return chain
    failed = summary_row.get("failed_providers") if isinstance(summary_row.get("failed_providers"), list) else []
    failed_chain = _joined_unique(_cell(item.get("provider")) for item in failed if isinstance(item, Mapping))
    provider_used = _cell(summary_row.get("provider_used"))
    return " -> ".join(item for item in (failed_chain, provider_used if provider_used != "n/a" else "") if item) or "not captured"


def _combined_status(attempts: Sequence[Mapping[str, Any]], key: str, fallback: object = None) -> str:
    values = [_cell(attempt.get(key)) for attempt in attempts if _cell(attempt.get(key)) != "n/a"]
    if values:
        if "failed" in values:
            return "failed"
        if "passed" in values:
            return "passed"
        return values[-1]
    return _cell(fallback) if _cell(fallback) != "n/a" else "not_reached"


def _attempt_error(attempt: Mapping[str, Any]) -> str:
    return _cell(attempt.get("error") or attempt.get("failure_reason") or attempt.get("network_exception"))


def _normal_status(status: object) -> str:
    return _cell(status)


def _root_cause(attempts: Sequence[Mapping[str, Any]], selected: Mapping[str, Any], output_written: bool) -> str:
    if output_written:
        return "none"
    causes = _joined_unique(_cell(attempt.get("failure_class")) for attempt in attempts if _cell(attempt.get("failure_class")) not in {"n/a", "none"})
    return causes or (_cell(selected.get("failure_class")) if _cell(selected.get("failure_class")) != "n/a" else "unknown")


def _failure_stage(selected: Mapping[str, Any], parser_status: str, validation_status: str, output_written: bool) -> str:
    if output_written:
        return "unknown"
    layer = str(selected.get("failure_layer") or "").upper()
    message = _attempt_error(selected).lower()
    status = selected.get("http_status")
    if "dns" in message or "name or service" in message or "name resolution" in message:
        return "DNS"
    if "tunnel connection failed" in message or "proxy" in message or "connect" in message:
        return "proxy CONNECT / tunnel"
    if "tls" in message or "ssl" in message or "certificate" in message:
        return "TLS"
    if status not in {None, "", "n/a"}:
        return "remote HTTP response"
    if layer in {"AUTH", "HTTP"}:
        return "remote HTTP response"
    if parser_status == "failed" or layer == "PARSER":
        return "parser"
    if validation_status == "failed" or layer in {"SCHEMA", "VALIDATION"}:
        return "validation"
    if layer == "NETWORK":
        return "proxy CONNECT / tunnel" if "tunnel" in message or "proxy" in message else "unknown"
    return "unknown"


def _executed(status: str) -> str:
    return "NO" if status in {"not_reached", "n/a", ""} else "YES"


def _joined_unique(values: Any) -> str:
    seen: list[str] = []
    for value in values:
        text = str(value)
        if text and text != "n/a" and text not in seen:
            seen.append(text)
    return " -> ".join(seen)


def _missing_dataset_names(manifest: Mapping[str, Any]) -> list[str]:
    missing = manifest.get("missing_production_csvs")
    if not isinstance(missing, list):
        return []
    return [str(item).removesuffix(".csv") for item in missing]


def _artifact_name(trade_date: str) -> str:
    return f"tdt-rm-production-fetch-{trade_date}"


def _env(name: str, default: str = "unknown") -> str:
    return os.environ.get(name, default) or default


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
                        row = _provider_health_attempt_row(dataset, attempt)
                        rows.append(row)
    return rows


def _provider_health_attempt_row(dataset: str, attempt: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(attempt)
    metadata = attempt.get("metadata") if isinstance(attempt.get("metadata"), Mapping) else {}
    url_fetch = metadata.get("url_fetch") if isinstance(metadata.get("url_fetch"), Mapping) else {}
    errors = url_fetch.get("errors") if isinstance(url_fetch.get("errors"), list) else []
    last_error = errors[-1] if errors and isinstance(errors[-1], Mapping) else {}
    row["provider_category"] = attempt.get("provider_category") or dataset
    row["source_id"] = attempt.get("source_id") or attempt.get("provider") or attempt.get("provider_id")
    row.setdefault("endpoint_attempted", metadata.get("endpoint") or url_fetch.get("final_url") or url_fetch.get("initial_url") or last_error.get("url"))
    row.setdefault("http_status", url_fetch.get("status") or last_error.get("status"))
    row.setdefault("network_exception", url_fetch.get("network_exception") or last_error.get("network_exception") or "")
    row.setdefault("rows_fetched", int(metadata.get("bar_count") or 0))
    if attempt.get("status") == "healthy":
        row.setdefault("parser_status", "passed")
        row.setdefault("validation_status", "passed")
        row.setdefault("failure_class", "none")
        row.setdefault("failure_layer", "NONE")
    else:
        row.setdefault("failure_layer", _failure_layer_from_attempt(row))
    if "success" not in row:
        row["success"] = attempt.get("status") == "healthy"
    return row


def _failure_layer_from_attempt(attempt: Mapping[str, Any]) -> str:
    message = str(attempt.get("error") or attempt.get("failure_reason") or attempt.get("network_exception") or "")
    lowered = message.lower()
    status = attempt.get("http_status")
    try:
        http_status = int(status) if status not in {None, ""} else None
    except (TypeError, ValueError):
        http_status = None
    if "finmind" in lowered and ("disabled" in lowered or "opt-in" in lowered or "token" in lowered):
        return "CONFIG" if "disabled" in lowered or "opt-in" in lowered else "AUTH"
    if any(token in lowered for token in ("tunnel connection failed", "proxy", "url fetch failed", "timed out", "dns", "connection", "network")):
        return "NETWORK"
    if http_status in {401, 403} or "token" in lowered or "auth" in lowered or "unauthorized" in lowered or "forbidden" in lowered:
        return "AUTH"
    if "schema" in lowered or "strict validation" in lowered:
        return "SCHEMA"
    if "parse" in lowered or "no row" in lowered or "returned 0" in lowered or "insufficient" in lowered or "stale" in lowered:
        return "PARSER"
    return "WORKFLOW"


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
