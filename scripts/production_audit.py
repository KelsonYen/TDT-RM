#!/usr/bin/env python
"""Fail-closed production readiness audit for existing TDT-RM artifacts only.

The audit intentionally reads previously generated production artifacts and does
not fetch provider data, assemble snapshots, run models, or recalculate scores.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

READY = "READY"
NOT_READY = "NOT_READY"
PASSED = "passed"
FAILED = "failed"

CHECK_NAMES = (
    "artifact_completeness",
    "manifest_completeness",
    "provider_health",
    "validation_status",
    "daily_report",
    "replay_readiness",
    "fail_closed_integrity",
)

DEFAULT_REQUIRED_PROVIDERS = ("price_provider",)
PASSING_PROVIDER_STATUSES = {"healthy", "warning", "passed", "ok"}
PASSING_FRESHNESS_STATUSES = {"passed", "fresh", "fresh_or_not_applicable", "not_applicable", "ok"}
PASSING_REPORT_STATUSES = {"passed", "success", "generated", "ok"}
KNOWN_REPLAY_FAILURE_CATEGORIES = {
    "success",
    "provider_failure",
    "validation_failure",
    "freshness_failure",
    "cache_failure",
    "fallback_failure",
    "snapshot_failure",
    "report_generation_failure",
    "unexpected_exception",
}
REQUIRED_REPORT_SECTIONS = (
    "Metadata",
    "Core Outputs",
    "Provider Health",
    "Validation Summary",
    "Final Decision",
)


@dataclass
class AuditContext:
    outputs_dir: Path
    trade_date: str
    audit_path: Path
    artifacts: dict[str, Path]
    loaded: dict[str, Any] = field(default_factory=dict)
    checks: dict[str, str] = field(default_factory=lambda: {name: PASSED for name in CHECK_NAMES})
    blocking_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def fail(self, check_name: str, message: str) -> None:
        self.checks[check_name] = FAILED
        if message not in self.blocking_errors:
            self.blocking_errors.append(message)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit TDT-RM production readiness from existing output artifacts only.")
    parser.add_argument("--outputs-dir", default="outputs", help="Directory containing production output artifacts.")
    parser.add_argument("--trade-date", required=True, help="Daily production trade date, YYYY-MM-DD.")
    parser.add_argument("--audit-path", help="Audit JSON path (default: <outputs-dir>/production_audit.json).")
    args = parser.parse_args(argv)

    try:
        outputs_dir = Path(args.outputs_dir)
        audit_path = Path(args.audit_path or outputs_dir / "production_audit.json")
        result = run_audit(outputs_dir=outputs_dir, trade_date=args.trade_date, audit_path=audit_path)
        print(render_cli_summary(result))
        return 0 if result["status"] == READY else 1
    except Exception as exc:  # noqa: BLE001 - CLI must distinguish script errors.
        print(f"ERROR {exc}", file=sys.stderr)
        return 2


def run_audit(*, outputs_dir: str | Path, trade_date: str, audit_path: str | Path) -> dict[str, Any]:
    """Run the production audit and write the JSON result.

    This function only reads artifacts under ``outputs_dir`` and writes the
    audit result. It does not call production fetchers, assemblers, validators,
    model code, or report/replay generators.
    """

    output_root = Path(outputs_dir)
    audit_destination = Path(audit_path)
    ctx = AuditContext(
        outputs_dir=output_root,
        trade_date=trade_date,
        audit_path=audit_destination,
        artifacts=_artifact_paths(output_root, trade_date),
    )

    _check_artifact_completeness(ctx)
    _load_available_artifacts(ctx)
    _check_manifest_completeness(ctx)
    _check_provider_health(ctx)
    _check_validation_status(ctx)
    _check_daily_report(ctx)
    _check_replay_readiness(ctx)
    _check_fail_closed_integrity(ctx)

    status = READY if not ctx.blocking_errors else NOT_READY
    result: dict[str, Any] = {
        "trade_date": trade_date,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "checks": dict(ctx.checks),
        "blocking_errors": list(ctx.blocking_errors),
        "warnings": list(ctx.warnings),
        "artifacts": {name: str(path) for name, path in ctx.artifacts.items()},
        "known_replay_failure_categories": sorted(KNOWN_REPLAY_FAILURE_CATEGORIES),
    }
    audit_destination.parent.mkdir(parents=True, exist_ok=True)
    audit_destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def render_cli_summary(result: Mapping[str, Any]) -> str:
    lines = ["Production Readiness Audit", "", f"Trade Date: {result.get('trade_date')}", f"Status: {result.get('status')}"]
    checks = result.get("checks")
    if isinstance(checks, Mapping):
        lines.extend(["", "Checks:"])
        for name in CHECK_NAMES:
            lines.append(f"{name}: {checks.get(name, FAILED)}")
    blocking_errors = [str(item) for item in _as_list(result.get("blocking_errors"))]
    warnings = [str(item) for item in _as_list(result.get("warnings"))]
    if blocking_errors:
        lines.extend(["", "Blocking Errors:"])
        lines.extend(blocking_errors)
    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(warnings)
    return "\n".join(lines) + "\n"


def _artifact_paths(outputs_dir: Path, trade_date: str) -> dict[str, Path]:
    return {
        "fetch_manifest": _find_existing(outputs_dir, ("fetch_manifest.json", "*_fetch_manifest.json")) or outputs_dir / "fetch_manifest.json",
        "provider_health": _find_existing(outputs_dir, ("provider_health.json", "*_provider_health.json")) or outputs_dir / "provider_health.json",
        "daily_validation": _find_existing(outputs_dir, ("daily_validation.json", f"daily_validation_{trade_date}.json", f"tdt_rm_daily_{trade_date}_manifest.json")) or outputs_dir / "daily_validation.json",
        "daily_report": _find_existing(outputs_dir, ("daily_report.md", f"daily_report_{trade_date}.md")) or outputs_dir / "daily_report.md",
        "replay_summary": outputs_dir / "replay" / "replay_summary.json",
        "replay_manifest": outputs_dir / "replay" / "replay_manifest.json",
        "replay_failures": outputs_dir / "replay" / "replay_failures.csv",
    }


def _find_existing(outputs_dir: Path, patterns: Sequence[str]) -> Path | None:
    for pattern in patterns:
        matches = sorted(outputs_dir.glob(pattern))
        for match in matches:
            if match.is_file():
                return match
    return None


def _check_artifact_completeness(ctx: AuditContext) -> None:
    for artifact_name, path in ctx.artifacts.items():
        if not path.exists():
            ctx.fail("artifact_completeness", f"required artifact {artifact_name} missing: {path}")


def _load_available_artifacts(ctx: AuditContext) -> None:
    for artifact_name in ("fetch_manifest", "provider_health", "daily_validation", "replay_summary", "replay_manifest"):
        path = ctx.artifacts[artifact_name]
        if not path.exists():
            continue
        try:
            ctx.loaded[artifact_name] = _load_json_object(path, artifact_name)
        except ValueError as exc:
            check = "replay_readiness" if artifact_name.startswith("replay_") else "artifact_completeness"
            ctx.fail(check, str(exc))


def _check_manifest_completeness(ctx: AuditContext) -> None:
    manifest = _mapping(ctx.loaded.get("fetch_manifest"))
    if not manifest:
        ctx.fail("manifest_completeness", "fetch manifest is missing or invalid")
        return

    manifest_trade_date = manifest.get("trade_date") or manifest.get("as_of")
    if not manifest_trade_date:
        ctx.fail("manifest_completeness", "fetch manifest missing trade_date/as_of")
    elif str(manifest_trade_date) != ctx.trade_date:
        ctx.fail("manifest_completeness", f"fetch manifest trade date {manifest_trade_date} does not match audit trade date {ctx.trade_date}")

    for field_name in ("generated_at",):
        if not manifest.get(field_name):
            ctx.fail("manifest_completeness", f"fetch manifest missing {field_name}")

    if not any(isinstance(manifest.get(field), (Mapping, list)) and bool(manifest.get(field)) for field in ("providers", "provider_health", "provider_csv_paths", "sources")):
        ctx.fail("manifest_completeness", "fetch manifest missing providers/provider_health/provider_csv_paths/sources")
    if not isinstance(manifest.get("provider_health_summary"), Mapping):
        ctx.fail("manifest_completeness", "fetch manifest missing provider health summary")

    report_status = _report_status(manifest)
    if not report_status:
        ctx.fail("manifest_completeness", "fetch manifest missing report generation status")
    elif report_status.lower() not in PASSING_REPORT_STATUSES:
        ctx.fail("manifest_completeness", f"daily report generation status is {report_status}")


def _check_provider_health(ctx: AuditContext) -> None:
    health = _mapping(ctx.loaded.get("provider_health"))
    providers = _mapping(health.get("providers"))
    if not providers:
        ctx.fail("provider_health", "provider health artifact missing providers")
        return

    required_providers = _required_providers(ctx)
    for provider_name in required_providers:
        provider = _mapping(providers.get(provider_name))
        if not provider:
            ctx.fail("provider_health", f"required provider {provider_name} missing from provider health")
            continue
        status = str(provider.get("status") or "").lower()
        freshness_status = str(provider.get("freshness_status") or "").lower()
        source_type = str(provider.get("source_type") or "")
        records_loaded = _safe_int(provider.get("records_loaded"))

        if status == "failed" or status not in PASSING_PROVIDER_STATUSES:
            ctx.fail("provider_health", f"required provider {provider_name} failed health status")
        if freshness_status == "failed" or freshness_status not in PASSING_FRESHNESS_STATUSES:
            ctx.fail("provider_health", f"required provider {provider_name} failed freshness validation")
        if records_loaded is None or records_loaded <= 0:
            ctx.fail("provider_health", f"required provider {provider_name} has no records_loaded")
        if not source_type:
            ctx.fail("provider_health", f"required provider {provider_name} missing source_type")
        _record_fallback_warning(ctx, provider_name, provider)

    for provider_name, raw_provider in providers.items():
        provider = _mapping(raw_provider)
        if provider:
            _record_fallback_warning(ctx, str(provider_name), provider)


def _required_providers(ctx: AuditContext) -> tuple[str, ...]:
    manifest = _mapping(ctx.loaded.get("fetch_manifest"))
    health = _mapping(ctx.loaded.get("provider_health"))
    candidates = manifest.get("required_providers") or health.get("required_providers")
    if isinstance(candidates, Sequence) and not isinstance(candidates, (str, bytes)):
        providers = tuple(str(item) for item in candidates if str(item))
        if providers:
            return providers
    return DEFAULT_REQUIRED_PROVIDERS


def _record_fallback_warning(ctx: AuditContext, provider_name: str, provider: Mapping[str, Any]) -> None:
    diagnostics = _mapping(provider.get("diagnostics"))
    fallback_used = (
        str(provider.get("source_type") or "").lower() == "local_fallback"
        or bool(provider.get("fallback_used"))
        or bool(diagnostics.get("fallback_attempted"))
        or str(diagnostics.get("source_selected_type") or "").lower() == "local_fallback"
    )
    if fallback_used:
        ctx.warn(f"{provider_name} used local_fallback")


def _check_validation_status(ctx: AuditContext) -> None:
    validation_artifact = _mapping(ctx.loaded.get("daily_validation"))
    if not validation_artifact:
        ctx.fail("validation_status", "daily validation artifact is missing or invalid")
        return
    validation = _mapping(validation_artifact.get("validation")) or validation_artifact
    passed = validation.get("validation_passed") if "validation_passed" in validation else validation.get("passed")
    status = str(validation.get("status") or validation_artifact.get("validation_status") or "").lower()
    blocking_errors = _as_list(validation.get("blocking_errors")) + _as_list(validation.get("errors"))
    stale_data_errors = _as_list(validation.get("stale_data_errors"))

    if passed is not True or status == "failed":
        ctx.fail("validation_status", "daily validation did not pass")
    if blocking_errors:
        ctx.fail("validation_status", "daily validation blocking_errors/errors not empty")
    if stale_data_errors:
        ctx.fail("validation_status", "daily validation stale_data_errors not empty")


def _check_daily_report(ctx: AuditContext) -> None:
    report_path = ctx.artifacts["daily_report"]
    if not report_path.exists():
        ctx.fail("daily_report", f"daily report missing: {report_path}")
        return
    report = report_path.read_text(encoding="utf-8")
    if "PRODUCTION REPORT FAILED" in report or "NOT FOR TRADING USE" in report:
        ctx.fail("daily_report", "daily report is a failed report")
    for section in REQUIRED_REPORT_SECTIONS:
        if not _report_contains_section(report, section):
            ctx.fail("daily_report", f"daily report missing required section: {section}")


def _report_contains_section(report: str, section: str) -> bool:
    lower_report = report.lower()
    lower_section = section.lower()
    if lower_section in lower_report:
        return True
    if section == "Core Outputs" and "core model outputs" in lower_report:
        return True
    if section == "Provider Health" and "provider health summary" in lower_report:
        return True
    return False


def _check_replay_readiness(ctx: AuditContext) -> None:
    summary = _mapping(ctx.loaded.get("replay_summary"))
    manifest = _mapping(ctx.loaded.get("replay_manifest"))
    failures_path = ctx.artifacts["replay_failures"]
    if not summary:
        ctx.fail("replay_readiness", "replay summary is missing or invalid")
        return
    if not manifest:
        ctx.fail("replay_readiness", "replay manifest is missing or invalid")
    if not failures_path.exists():
        ctx.fail("replay_readiness", f"replay failures CSV missing: {failures_path}")
        return

    total_days = _safe_int(summary.get("total_days"))
    if total_days is None or total_days <= 0:
        ctx.fail("replay_readiness", "replay total_days must be greater than 0")
    if "failed_runs" not in summary:
        ctx.fail("replay_readiness", "replay failed_runs not recorded")

    categories = set()
    status_counts = summary.get("status_counts")
    if isinstance(status_counts, Mapping):
        categories.update(str(key) for key in status_counts)
    try:
        with failures_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                failure_type = str(row.get("failure_type") or "")
                if failure_type:
                    categories.add(failure_type)
    except csv.Error as exc:
        ctx.fail("replay_readiness", f"replay failures CSV invalid: {exc}")

    unknown = sorted(category for category in categories if category not in KNOWN_REPLAY_FAILURE_CATEGORIES)
    if unknown:
        ctx.fail("replay_readiness", f"replay failure categories unknown: {', '.join(unknown)}")


def _check_fail_closed_integrity(ctx: AuditContext) -> None:
    if any(ctx.checks[name] == FAILED for name in CHECK_NAMES if name != "fail_closed_integrity"):
        ctx.fail("fail_closed_integrity", "one or more production readiness checks failed closed")


def _report_status(manifest: Mapping[str, Any]) -> str:
    daily_report = _mapping(manifest.get("daily_report")) or _mapping(manifest.get("report_generation"))
    return str(daily_report.get("status") or manifest.get("report_generation_status") or "")


def _load_json_object(path: Path, artifact_name: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{artifact_name} is not valid JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"{artifact_name} JSON root must be an object")
    return dict(payload)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _safe_int(value: Any) -> int | None:
    try:
        if isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
