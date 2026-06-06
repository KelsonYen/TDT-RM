"""Production-readiness validation for TDT-RM daily artifacts.

The checks in this module validate artifact completeness and operator-readiness
only. They intentionally do not recalculate or alter model scoring outputs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, Mapping

ValidationSeverity = Literal["warning", "error"]
ValidationStatus = Literal["passed", "warning", "failed"]

KNOWN_FIVE_LIGHT_SIGNALS = {"Green", "Yellow", "Strengthened Yellow", "Orange", "Red"}
REQUIRED_TOP_LEVEL_FIELDS = {
    "timestamp",
    "model_version",
    "trade_date",
    "market_regime",
    "tcwrs",
    "mhs",
    "eti_5",
    "tail_risk",
    "bcd",
    "cp",
    "cp_level",
    "signal",
    "equity_exposure_limit",
    "inputs",
    "scores",
    "traces",
    "data",
    "etf_exit",
}
REQUIRED_SCORE_FIELDS = {"TCWRS", "MHS", "ETI-5", "Tail Risk", "BCD", "CP"}
REQUIRED_TRACE_FIELDS = {"tcwrs", "eti_5", "crash_probability", "bear_trend", "decision_matrix"}
PRICE_ONLY_PROVISIONAL_STATUS = "price_only_provisional"
STALE_WARNING_DAYS = 1
STALE_ERROR_DAYS = 3


@dataclass(frozen=True)
class DailyValidationIssue:
    """One production-readiness warning or blocking error."""

    severity: ValidationSeverity
    code: str
    message: str
    field: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "field": self.field,
        }


@dataclass(frozen=True)
class DailyValidationResult:
    """Aggregated validation outcome for one daily payload/artifact pair."""

    issues: tuple[DailyValidationIssue, ...] = field(default_factory=tuple)

    @property
    def errors(self) -> tuple[DailyValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[DailyValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    @property
    def passed(self) -> bool:
        return not self.has_errors

    @property
    def status(self) -> ValidationStatus:
        if self.errors:
            return "failed"
        if self.warnings:
            return "warning"
        return "passed"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "passed": self.passed,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": [issue.as_dict() for issue in self.errors],
            "warnings": [issue.as_dict() for issue in self.warnings],
            "issues": [issue.as_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class DailyRunManifest:
    """Run manifest attached to a validated daily production run."""

    run_timestamp: str
    model_version: str | None
    trade_date: str | None
    data_source: str | None
    data_status: str | None
    artifact_paths: Mapping[str, str]
    validation: Mapping[str, Any]
    data_quality: Mapping[str, Any] = field(default_factory=dict)
    command: str | None = None
    git_sha: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_timestamp": self.run_timestamp,
            "model_version": self.model_version,
            "trade_date": self.trade_date,
            "data_source": self.data_source,
            "data_status": self.data_status,
            "artifact_paths": dict(self.artifact_paths),
            "validation_status": self.validation.get("status"),
            "validation": dict(self.validation),
            "data_quality": dict(self.data_quality),
            "command": self.command,
            "git_sha": self.git_sha,
        }


def validate_daily_payload(payload: Mapping[str, Any], *, as_of: date | None = None) -> DailyValidationResult:
    """Validate daily JSON payload readiness without changing scoring values."""

    issues: list[DailyValidationIssue] = []
    missing = sorted(REQUIRED_TOP_LEVEL_FIELDS - set(payload))
    for field_name in missing:
        issues.append(_error("missing_required_field", f"Required top-level field is missing: {field_name}", field_name))

    trade_date = _parse_optional_date(payload.get("trade_date"), "trade_date", issues)
    signal = payload.get("signal")
    if signal not in KNOWN_FIVE_LIGHT_SIGNALS:
        issues.append(
            _error(
                "unknown_signal",
                f"Signal must be one of {sorted(KNOWN_FIVE_LIGHT_SIGNALS)}; got {signal!r}",
                "signal",
            )
        )

    if not payload.get("equity_exposure_limit"):
        issues.append(_error("empty_equity_exposure_limit", "Equity exposure limit is missing or empty", "equity_exposure_limit"))

    data = payload.get("data")
    if isinstance(data, Mapping):
        latest_bar_date = _parse_optional_date(data.get("latest_bar_date"), "data.latest_bar_date", issues)
        if trade_date is not None and latest_bar_date is not None and latest_bar_date != trade_date:
            issues.append(
                _error(
                    "latest_bar_date_mismatch",
                    f"data.latest_bar_date {latest_bar_date} must equal trade_date {trade_date}",
                    "data.latest_bar_date",
                )
            )
        bar_count = data.get("bar_count")
        if not isinstance(bar_count, int) or isinstance(bar_count, bool) or bar_count < 61:
            issues.append(_error("insufficient_bar_count", "data.bar_count must be an integer >= 61", "data.bar_count"))
        if "status" not in data or not data.get("status"):
            issues.append(_error("missing_data_status", "data.status is required", "data.status"))
        elif data.get("status") == PRICE_ONLY_PROVISIONAL_STATUS:
            issues.append(
                _warning(
                    "price_only_provisional",
                    "Data status is price_only_provisional; operator output is usable with the documented price-only limitations.",
                    "data.status",
                )
            )
    elif "data" not in missing:
        issues.append(_error("invalid_data_section", "data must be a mapping", "data"))

    _validate_mapping_keys(payload.get("scores"), REQUIRED_SCORE_FIELDS, "scores", issues)
    _validate_mapping_keys(payload.get("traces"), REQUIRED_TRACE_FIELDS, "traces", issues)
    _validate_etf_exit(payload.get("etf_exit"), issues)
    _validate_staleness(trade_date, as_of, issues)
    return DailyValidationResult(tuple(issues))


def validate_daily_artifacts(
    json_path: str | Path,
    markdown_path: str | Path,
    *,
    as_of: date | None = None,
) -> DailyValidationResult:
    """Validate a JSON daily artifact and its Markdown companion."""

    issues: list[DailyValidationIssue] = []
    json_artifact = Path(json_path)
    markdown_artifact = Path(markdown_path)
    payload: Mapping[str, Any] | None = None

    if not json_artifact.exists():
        issues.append(_error("missing_json_artifact", f"JSON artifact does not exist: {json_artifact}", "json_path"))
    else:
        try:
            loaded = json.loads(json_artifact.read_text(encoding="utf-8"))
            if isinstance(loaded, Mapping):
                payload = loaded
            else:
                issues.append(_error("invalid_json_payload", "JSON artifact root must be an object", "json_path"))
        except json.JSONDecodeError as exc:
            issues.append(_error("invalid_json", f"JSON artifact is not valid JSON: {exc}", "json_path"))

    if payload is not None:
        issues.extend(validate_daily_payload(payload, as_of=as_of).issues)

    if not markdown_artifact.exists():
        issues.append(_error("missing_markdown_artifact", f"Markdown artifact does not exist: {markdown_artifact}", "markdown_path"))
    elif payload is not None:
        markdown = markdown_artifact.read_text(encoding="utf-8")
        trade_date = str(payload.get("trade_date", ""))
        signal = str(payload.get("signal", ""))
        slash_trade_date = trade_date.replace("-", "/")
        if trade_date and trade_date not in markdown and slash_trade_date not in markdown:
            issues.append(_error("markdown_trade_date_mismatch", f"Markdown artifact does not reference trade_date {trade_date}", "markdown_path"))
        localized_signal = _localized_signal(signal)
        if signal and signal not in markdown and localized_signal not in markdown:
            issues.append(_error("markdown_signal_mismatch", f"Markdown artifact does not reference signal {signal}", "markdown_path"))

    return DailyValidationResult(tuple(issues))



def _localized_signal(signal: str) -> str:
    return {
        "Green": "綠燈",
        "Yellow": "黃燈",
        "Strengthened Yellow": "強化黃燈",
        "Orange": "橘燈",
        "Red": "紅燈",
        "Deep Red": "紅燈",
    }.get(signal, signal)

def build_daily_run_manifest(
    payload: Mapping[str, Any],
    json_path: str | Path,
    markdown_path: str | Path,
    *,
    command: str | None = None,
    git_sha: str | None = None,
    validation: DailyValidationResult | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a serializable manifest for a daily run and its validation gate."""

    validation_dict = _validation_as_dict(validation or validate_daily_artifacts(json_path, markdown_path))
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
    manifest = DailyRunManifest(
        run_timestamp=_utc_now_iso(),
        model_version=_optional_str(payload.get("model_version")),
        trade_date=_optional_str(payload.get("trade_date")),
        data_source=_optional_str(data.get("source")),
        data_status=_optional_str(data.get("status")),
        artifact_paths={"json": str(Path(json_path)), "markdown": str(Path(markdown_path))},
        validation=validation_dict,
        data_quality={
            "fallback_proxies": dict(data.get("fallback_proxies", {})) if isinstance(data.get("fallback_proxies"), Mapping) else {},
            "field_sources": dict(data.get("field_sources", {})) if isinstance(data.get("field_sources"), Mapping) else {},
            "source_metadata": dict(data.get("source_metadata", {})) if isinstance(data.get("source_metadata"), Mapping) else {},
            "missing_fields": list(data.get("missing_fields", [])) if isinstance(data.get("missing_fields", []), list) else [],
            "available_eti_components": list(data.get("available_eti_components", [])) if isinstance(data.get("available_eti_components", []), list) else [],
            "data_status": data.get("data_status") or data.get("status"),
        },
        command=command,
        git_sha=git_sha,
    )
    return manifest.as_dict()


def _validate_mapping_keys(
    value: Any,
    required_keys: set[str],
    field_name: str,
    issues: list[DailyValidationIssue],
) -> None:
    if not isinstance(value, Mapping):
        issues.append(_error(f"invalid_{field_name}", f"{field_name} must be a mapping", field_name))
        return
    missing = sorted(required_keys - set(value))
    for key in missing:
        issues.append(_error(f"missing_{field_name}_field", f"{field_name} is missing required field: {key}", f"{field_name}.{key}"))


def _validate_etf_exit(value: Any, issues: list[DailyValidationIssue]) -> None:
    if not isinstance(value, Mapping):
        issues.append(_error("invalid_etf_exit", "etf_exit must be a mapping", "etf_exit"))
        return
    enabled = value.get("enabled")
    status = value.get("status")
    notes = str(value.get("notes", ""))
    if enabled is False and status != "not_integrated":
        issues.append(_error("etf_exit_placeholder_not_explicit", "ETF Exit placeholder must use status='not_integrated' when disabled", "etf_exit.status"))
    if enabled is False and not notes:
        issues.append(_error("etf_exit_notes_missing", "ETF Exit placeholder must include explanatory notes", "etf_exit.notes"))


def _validate_staleness(
    trade_date: date | None,
    as_of: date | None,
    issues: list[DailyValidationIssue],
) -> None:
    if trade_date is None or as_of is None:
        return
    age_days = (as_of - trade_date).days
    if age_days < 0:
        issues.append(_error("future_trade_date", f"trade_date {trade_date} is after as_of {as_of}", "trade_date"))
    elif age_days > STALE_ERROR_DAYS:
        issues.append(_error("stale_trade_date", f"trade_date {trade_date} is {age_days} days behind as_of {as_of}", "trade_date"))
    elif age_days >= STALE_WARNING_DAYS:
        issues.append(_warning("stale_trade_date", f"trade_date {trade_date} is {age_days} day(s) behind as_of {as_of}", "trade_date"))


def _parse_optional_date(value: Any, field_name: str, issues: list[DailyValidationIssue]) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        issues.append(_error("invalid_date", f"{field_name} must be an ISO date; got {value!r}", field_name))
        return None


def _validation_as_dict(validation: DailyValidationResult | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(validation, DailyValidationResult):
        return validation.as_dict()
    return dict(validation)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _error(code: str, message: str, field: str | None = None) -> DailyValidationIssue:
    return DailyValidationIssue("error", code, message, field)


def _warning(code: str, message: str, field: str | None = None) -> DailyValidationIssue:
    return DailyValidationIssue("warning", code, message, field)
