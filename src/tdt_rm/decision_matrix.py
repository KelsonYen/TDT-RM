"""Five-light decision matrix for TDT-RM V5.1.3 Rev.3 Final Freeze."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

SignalColor = Literal["Red", "Orange", "Strengthened Yellow", "Yellow", "Green"]


@dataclass(frozen=True)
class DecisionMatrixInput:
    """Inputs needed by the frozen five-light decision matrix.

    ``mhs`` is optional for backtests focused on TCWRS/ETI-5/TailRisk/BCD; when
    omitted it is treated as neutral so it cannot upgrade a signal.
    """

    tcwrs: float
    eti5_total: int
    tail_risk: float
    bcd: float
    taiex: float
    ma20: float
    consecutive_down_days: int
    mhs: float = 0.0


@dataclass(frozen=True)
class DecisionMatrixResult:
    """First-match five-light signal with an auditable rule trace."""

    signal: SignalColor
    equity_exposure_limit: str
    matched_rule: str
    trace_output: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "equity_exposure_limit": self.equity_exposure_limit,
            "matched_rule": self.matched_rule,
            "trace_output": dict(self.trace_output),
        }


def resolve_five_light_signal(data: DecisionMatrixInput) -> DecisionMatrixResult:
    """Apply the frozen decision order: red, orange, strengthened yellow, yellow, green."""

    bcd_confirmation_valid = (
        data.bcd >= 61 and data.taiex > data.ma20 and data.consecutive_down_days <= 3
    )
    trace = {
        "tcwrs": data.tcwrs,
        "eti5_total": data.eti5_total,
        "tail_risk": data.tail_risk,
        "bcd": data.bcd,
        "taiex": data.taiex,
        "ma20": data.ma20,
        "consecutive_down_days": data.consecutive_down_days,
        "mhs": data.mhs,
        "bcd_confirmation_valid": bcd_confirmation_valid,
    }

    red_rules = (
        (data.tcwrs >= 76, "TCWRS >= 76"),
        (data.eti5_total >= 4, "ETI5_total >= 4"),
        (data.tcwrs >= 61 and data.eti5_total >= 3, "TCWRS >= 61 AND ETI5_total >= 3"),
    )
    for matched, rule in red_rules:
        if matched:
            return _result("Red", "20-30% or below", rule, trace)

    orange_rules = (
        (61 <= data.tcwrs <= 75 and data.eti5_total >= 2, "61 <= TCWRS <= 75 AND ETI5_total >= 2"),
        (data.eti5_total >= 3 and data.tcwrs >= 41, "ETI5_total >= 3 AND TCWRS >= 41"),
        (data.tcwrs >= 41 and data.tail_risk >= 61 and data.eti5_total >= 2, "TCWRS >= 41 AND TailRisk >= 61 AND ETI5_total >= 2"),
        (bcd_confirmation_valid and data.tcwrs >= 41 and data.eti5_total >= 2, "BCD >= 61 AND TCWRS >= 41 AND ETI5_total >= 2 AND TAIEX > MA20 AND consecutive_down_days <= 3"),
    )
    for matched, rule in orange_rules:
        if matched:
            return _result("Orange", "40-50%", rule, trace)

    strengthened_yellow_rules = (
        (41 <= data.tcwrs <= 60, "41 <= TCWRS <= 60"),
        (data.mhs >= 86 and data.tcwrs >= 30, "MHS >= 86 AND TCWRS >= 30"),
        (data.eti5_total >= 2 and data.tcwrs >= 21, "ETI5_total >= 2 AND TCWRS >= 21"),
        (data.tail_risk >= 61 and data.tcwrs >= 21, "TailRisk >= 61 AND TCWRS >= 21"),
        (bcd_confirmation_valid and data.tcwrs >= 21, "BCD >= 61 AND TCWRS >= 21 AND TAIEX > MA20 AND consecutive_down_days <= 3"),
    )
    for matched, rule in strengthened_yellow_rules:
        if matched:
            return _result("Strengthened Yellow", "50-70%", rule, trace)

    yellow_rules = (
        (21 <= data.tcwrs <= 40, "21 <= TCWRS <= 40"),
        (data.mhs >= 71, "MHS >= 71"),
        (data.eti5_total >= 1, "ETI5_total >= 1"),
        (data.tail_risk >= 41, "TailRisk >= 41"),
        (data.bcd >= 41, "BCD >= 41"),
    )
    for matched, rule in yellow_rules:
        if matched:
            return _result("Yellow", "60-80%", rule, trace)

    return _result("Green", "80-100%", "Default/green light conditions", trace)


def _result(signal: SignalColor, exposure: str, rule: str, trace: Mapping[str, Any]) -> DecisionMatrixResult:
    return DecisionMatrixResult(
        signal=signal,
        equity_exposure_limit=exposure,
        matched_rule=rule,
        trace_output=trace,
    )
