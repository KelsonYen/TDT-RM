"""Five-light decision matrix for TDT-RM V5.1.4 Backtest Calibration Patch."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

SignalColor = Literal["Red", "Orange", "Strengthened Yellow", "Yellow", "Green"]

_SIGNAL_RANK: dict[SignalColor, int] = {
    "Green": 0,
    "Yellow": 1,
    "Strengthened Yellow": 2,
    "Orange": 3,
    "Red": 4,
}
_EXPOSURE_LIMITS: dict[SignalColor, str] = {
    "Green": "80-100%",
    "Yellow": "60-80%",
    "Strengthened Yellow": "50-70%",
    "Orange": "40-50%",
    "Red": "20-30% or below",
}


@dataclass(frozen=True)
class DecisionMatrixInput:
    """Inputs needed by the V5.1.4 calibrated five-light decision matrix.

    ``eti5_total`` should be the capped/effective ETI-5 score when a calibrated
    ETI-5 result is available. ``eti_available_count`` is used to block ETI-only
    red-light decisions when fewer than three ETI components are available.
    ``cp_score`` can confirm a red light but never creates a red light by itself.
    """

    tcwrs: float
    eti5_total: int
    tail_risk: float
    bcd: float
    taiex: float
    ma20: float
    consecutive_down_days: int
    mhs: float = 0.0
    cp_score: float | None = None
    eti_available_count: int | None = None


@dataclass(frozen=True)
class BearTrendInput:
    """Inputs for the V5.1.4 Bear Trend Filter."""

    close: float
    ma20: float
    ma60: float
    previous_ma60: float
    return_60d_pct: float


@dataclass(frozen=True)
class BearTrendResult:
    """Bear Trend Filter result used as a five-light floor, not TCWRS input."""

    score: int
    floor_signal: SignalColor | None
    conditions: Mapping[str, bool]

    def as_dict(self) -> dict[str, Any]:
        return {
            "bear_trend_score": self.score,
            "bear_trend_floor_signal": self.floor_signal,
            "conditions": dict(self.conditions),
        }


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


def score_bear_trend_filter(data: BearTrendInput) -> BearTrendResult:
    """Score the V5.1.4 slow-bear filter and return the required signal floor."""

    conditions = {
        "close_below_ma60": data.close < data.ma60,
        "ma20_below_ma60": data.ma20 < data.ma60,
        "ma60_turning_down": data.ma60 < data.previous_ma60,
        "return_60d_negative": data.return_60d_pct < 0,
    }
    score = sum(conditions.values())
    floor: SignalColor | None
    if score >= 4:
        floor = "Orange"
    elif score == 3:
        floor = "Strengthened Yellow"
    elif score == 2:
        floor = "Yellow"
    else:
        floor = None
    return BearTrendResult(score=score, floor_signal=floor, conditions=conditions)


def apply_signal_floor(signal: SignalColor, floor_signal: SignalColor | None) -> SignalColor:
    """Raise ``signal`` to ``floor_signal`` when the floor is more conservative."""

    if floor_signal is None or _SIGNAL_RANK[signal] >= _SIGNAL_RANK[floor_signal]:
        return signal
    return floor_signal


def resolve_five_light_signal(
    data: DecisionMatrixInput,
    bear_trend: BearTrendResult | None = None,
) -> DecisionMatrixResult:
    """Apply V5.1.4 rules: red, orange, strengthened yellow, yellow, green, then bear floor."""

    trace = {
        "tcwrs": data.tcwrs,
        "eti5_total": data.eti5_total,
        "eti_available_count": data.eti_available_count,
        "tail_risk": data.tail_risk,
        "bcd": data.bcd,
        "taiex": data.taiex,
        "ma20": data.ma20,
        "consecutive_down_days": data.consecutive_down_days,
        "mhs": data.mhs,
        "cp_score": data.cp_score,
        "cp_red_confirmation": data.cp_score is not None and data.cp_score >= 55,
        "bear_trend": bear_trend.as_dict() if bear_trend is not None else None,
    }
    eti_available_count = data.eti_available_count if data.eti_available_count is not None else 5
    eti_red_allowed = eti_available_count >= 3

    red_rules = (
        (data.tcwrs >= 76, "TCWRS >= 76", "TCWRS"),
        (data.eti5_total >= 4 and data.tcwrs >= 41 and eti_red_allowed, "ETI5_total >= 4 AND TCWRS >= 41", "ETI-5+TCWRS"),
        (data.tcwrs >= 61 and data.eti5_total >= 3 and eti_red_allowed, "TCWRS >= 61 AND ETI5_total >= 3", "TCWRS+ETI-5"),
    )
    for matched, rule, confirmed_by in red_rules:
        if matched:
            trace["red_confirmed_by"] = _append_cp_confirmation(confirmed_by, data.cp_score)
            return _with_floor("Red", rule, trace, bear_trend)

    orange_rules = (
        (61 <= data.tcwrs <= 75 and data.eti5_total >= 2, "61 <= TCWRS <= 75 AND ETI5_total >= 2"),
        (data.eti5_total >= 3 and data.tcwrs >= 41, "ETI5_total >= 3 AND TCWRS >= 41"),
        (data.tcwrs >= 41 and data.tail_risk >= 61 and data.eti5_total >= 2, "TCWRS >= 41 AND TailRisk >= 61 AND ETI5_total >= 2"),
        (data.bcd >= 61 and data.tcwrs >= 41 and data.eti5_total >= 2, "BCD >= 61 AND TCWRS >= 41 AND ETI5_total >= 2"),
        (data.eti5_total >= 4 and data.tcwrs < 41, "ETI5_total >= 4 AND TCWRS < 41; downgraded to Orange"),
    )
    for matched, rule in orange_rules:
        if matched:
            trace["red_confirmed_by"] = None
            return _with_floor("Orange", rule, trace, bear_trend)

    strengthened_yellow_rules = (
        (41 <= data.tcwrs <= 60, "41 <= TCWRS <= 60"),
        (data.mhs >= 86 and data.tcwrs >= 30, "MHS >= 86 AND TCWRS >= 30"),
        (data.eti5_total >= 2 and data.tcwrs >= 21, "ETI5_total >= 2 AND TCWRS >= 21"),
        (data.tail_risk >= 61 and data.tcwrs >= 21, "TailRisk >= 61 AND TCWRS >= 21"),
        (data.bcd >= 61 and data.tcwrs >= 21, "BCD >= 61 AND TCWRS >= 21"),
    )
    for matched, rule in strengthened_yellow_rules:
        if matched:
            trace["red_confirmed_by"] = None
            return _with_floor("Strengthened Yellow", rule, trace, bear_trend)

    yellow_rules = (
        (21 <= data.tcwrs <= 40, "21 <= TCWRS <= 40"),
        (data.mhs >= 71, "MHS >= 71"),
        (data.eti5_total >= 1, "ETI5_total >= 1"),
        (data.tail_risk >= 41, "TailRisk >= 41"),
        (data.bcd >= 41, "BCD >= 41"),
    )
    for matched, rule in yellow_rules:
        if matched:
            trace["red_confirmed_by"] = None
            return _with_floor("Yellow", rule, trace, bear_trend)

    trace["red_confirmed_by"] = None
    return _with_floor("Green", "Default/green light conditions", trace, bear_trend)


def _append_cp_confirmation(confirmed_by: str, cp_score: float | None) -> str:
    if cp_score is not None and cp_score >= 55:
        return f"{confirmed_by}+CP>=55"
    return confirmed_by


def _with_floor(signal: SignalColor, rule: str, trace: dict[str, Any], bear_trend: BearTrendResult | None) -> DecisionMatrixResult:
    floor_signal = bear_trend.floor_signal if bear_trend is not None else None
    floored_signal = apply_signal_floor(signal, floor_signal)
    resolved_rule = rule
    if floored_signal != signal:
        resolved_rule = f"{rule}; Bear Trend Filter floor -> {floored_signal}"
    resolved_trace = dict(trace)
    resolved_trace["signal_before_bear_trend_floor"] = signal
    resolved_trace["signal_after_bear_trend_floor"] = floored_signal
    return _result(floored_signal, _EXPOSURE_LIMITS[floored_signal], resolved_rule, resolved_trace)


def _result(signal: SignalColor, exposure: str, rule: str, trace: Mapping[str, Any]) -> DecisionMatrixResult:
    return DecisionMatrixResult(
        signal=signal,
        equity_exposure_limit=exposure,
        matched_rule=rule,
        trace_output=trace,
    )
