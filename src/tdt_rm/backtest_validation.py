"""Validation helpers for generated TDT-RM historical backtest artifacts."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class BacktestValidationCheck:
    """One auditable validation check for a generated backtest artifact."""

    name: str
    passed: bool
    message: str
    details: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable validation check."""

        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class BacktestValidationResult:
    """Aggregate validation result for a generated backtest CSV/summary pair."""

    checks: Sequence[BacktestValidationCheck]

    @property
    def is_valid(self) -> bool:
        """Return true when every validation check passed."""

        return all(check.passed for check in self.checks)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable validation summary."""

        return {
            "is_valid": self.is_valid,
            "checks": [check.as_dict() for check in self.checks],
        }


def validate_2022_bear_market_backtest(
    csv_path: str | Path,
    summary_path: str | Path | None = None,
) -> BacktestValidationResult:
    """Validate the V5.1.4 2022 bear-market backtest acceptance gates.

    The validation is intentionally artifact-based so it can be run after the
    executable backtest script and catch CSV/summary drift, stale reports, or
    accidental reintroduction of the V5.1.3 price-only ETI over-promotion bug.
    """

    rows = _load_csv_rows(csv_path)
    summary = _load_summary(summary_path) if summary_path is not None else None

    checks = [
        _check_observation_window(rows),
        _check_required_columns(rows),
        _check_price_only_eti_controls(rows),
        _check_red_signal_confirmation(rows),
        _check_outcome_annotations(rows),
    ]
    if summary is not None:
        checks.append(_check_summary_matches_rows(rows, summary))

    return BacktestValidationResult(checks=checks)


def _load_csv_rows(csv_path: str | Path) -> list[dict[str, str]]:
    with Path(csv_path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _load_summary(summary_path: str | Path) -> dict[str, Any]:
    return json.loads(Path(summary_path).read_text(encoding="utf-8"))


def _check_observation_window(rows: Sequence[Mapping[str, str]]) -> BacktestValidationCheck:
    dates = [row.get("Date", "") for row in rows]
    passed = (
        len(rows) == 247
        and dates[:1] == ["2022-01-03"]
        and dates[-1:] == ["2022-12-30"]
    )
    return BacktestValidationCheck(
        name="observation_window",
        passed=passed,
        message="CSV contains the expected 247-session 2022 bear-market window."
        if passed
        else "CSV does not match the expected 2022 bear-market observation window.",
        details={
            "observations": len(rows),
            "first_date": dates[0] if dates else None,
            "last_date": dates[-1] if dates else None,
            "expected_observations": 247,
            "expected_first_date": "2022-01-03",
            "expected_last_date": "2022-12-30",
        },
    )


def _check_required_columns(rows: Sequence[Mapping[str, str]]) -> BacktestValidationCheck:
    required = {
        "Date",
        "TCWRS",
        "ETI-5",
        "eti_available_count",
        "eti_raw_score",
        "eti_capped_score",
        "eti_cap_reason",
        "Signal",
        "Close",
        "forward_20d_max_drawdown",
        "forward_40d_max_drawdown",
        "forward_60d_max_drawdown",
        "false_positive_20d",
        "false_positive_40d",
        "false_positive_60d",
        "delayed_valid_signal",
        "False Positive",
        "Drawdown Avoided %",
    }
    present = set(rows[0].keys()) if rows else set()
    missing = sorted(required - present)
    return BacktestValidationCheck(
        name="required_columns",
        passed=not missing,
        message="CSV includes all V5.1.4 validation/audit columns."
        if not missing
        else "CSV is missing required V5.1.4 validation/audit columns.",
        details={"missing_columns": missing, "required_columns": sorted(required)},
    )


def _check_price_only_eti_controls(rows: Sequence[Mapping[str, str]]) -> BacktestValidationCheck:
    violations = []
    for row in rows:
        available = _int_value(row, "eti_available_count")
        capped = _int_value(row, "eti_capped_score")
        raw = _int_value(row, "eti_raw_score")
        score = _int_value(row, "ETI-5")
        if available != 1 or score != capped or raw is None or capped is None or capped > 2:
            violations.append(row.get("Date"))
        if row.get("eti_cap_reason") != "available components <= 2; capped at 2":
            violations.append(row.get("Date"))
    passed = not violations
    return BacktestValidationCheck(
        name="price_only_eti_controls",
        passed=passed,
        message="Price-only tape keeps only ETI-1 available and applies the V5.1.4 ETI cap."
        if passed
        else "At least one row violates the price-only ETI availability/cap controls.",
        details={"violation_dates": violations[:20], "violation_count": len(violations)},
    )


def _check_red_signal_confirmation(rows: Sequence[Mapping[str, str]]) -> BacktestValidationCheck:
    violations = []
    red_count = 0
    for row in rows:
        if row.get("Signal") != "Red":
            continue
        red_count += 1
        tcwrs = _float_value(row, "TCWRS")
        available = _int_value(row, "eti_available_count")
        confirmed_by = row.get("red_confirmed_by", "")
        if not (tcwrs is not None and tcwrs >= 76) and not (
            available is not None and available >= 3 and confirmed_by
        ):
            violations.append(row.get("Date"))
    passed = not violations
    return BacktestValidationCheck(
        name="red_signal_confirmation",
        passed=passed,
        message="No red signal is created by unavailable ETI components or CP alone."
        if passed
        else "At least one red signal lacks TCWRS or full-ETI confirmation.",
        details={
            "red_signals": red_count,
            "violation_dates": violations[:20],
            "violation_count": len(violations),
        },
    )


def _check_outcome_annotations(rows: Sequence[Mapping[str, str]]) -> BacktestValidationCheck:
    invalid_dates = []
    for row in rows:
        fields: Iterable[str] = (
            "forward_20d_max_drawdown",
            "forward_40d_max_drawdown",
            "forward_60d_max_drawdown",
            "Drawdown Avoided %",
        )
        if any(_float_value(row, field) is None for field in fields):
            invalid_dates.append(row.get("Date"))
            continue
        bool_fields = (
            "false_positive_20d",
            "false_positive_40d",
            "false_positive_60d",
            "delayed_valid_signal",
            "False Positive",
        )
        if any(row.get(field) not in {"True", "False"} for field in bool_fields):
            invalid_dates.append(row.get("Date"))
    passed = not invalid_dates
    return BacktestValidationCheck(
        name="outcome_annotations",
        passed=passed,
        message="Forward drawdown and false-positive annotations are populated for every row."
        if passed
        else "At least one row has missing or malformed outcome annotations.",
        details={"invalid_dates": invalid_dates[:20], "invalid_count": len(invalid_dates)},
    )


def _check_summary_matches_rows(
    rows: Sequence[Mapping[str, str]],
    summary: Mapping[str, Any],
) -> BacktestValidationCheck:
    red = sum(row.get("Signal") == "Red" for row in rows)
    orange = sum(row.get("Signal") == "Orange" for row in rows)
    false_positive = sum(row.get("False Positive") == "True" for row in rows)
    max_avoided = max(
        (_float_value(row, "Drawdown Avoided %") or 0.0 for row in rows),
        default=0.0,
    )
    expected = {
        "observations": len(rows),
        "red_signals": red,
        "orange_signals": orange,
        "false_positives": false_positive,
        "maximum_drawdown_avoided_pct": round(max_avoided, 2),
    }
    mismatches = {
        key: {"summary": summary.get(key), "csv": value}
        for key, value in expected.items()
        if summary.get(key) != value
    }
    return BacktestValidationCheck(
        name="summary_matches_rows",
        passed=not mismatches,
        message="Summary JSON agrees with the generated CSV aggregates."
        if not mismatches
        else "Summary JSON does not agree with the generated CSV aggregates.",
        details={"mismatches": mismatches, "expected": expected},
    )


def _int_value(row: Mapping[str, str], field: str) -> int | None:
    value = _float_value(row, field)
    if value is None:
        return None
    return int(value)


def _float_value(row: Mapping[str, str], field: str) -> float | None:
    try:
        return float(row[field])
    except (KeyError, TypeError, ValueError):
        return None
