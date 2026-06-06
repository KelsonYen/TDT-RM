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
    bcd: float | None
    taiex: float
    ma20: float
    consecutive_down_days: int
    mhs: float = 0.0
    bcd_status: str = "COMPLETE"
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
class CrashAccelerationInput:
    """Inputs for the Crash Acceleration Layer (CAL) acute-crash override.

    CAL is intentionally velocity-gated: slow bear-market deterioration alone
    must not produce a CAL score or floor. Returns are percentages, where
    downside moves are negative. ``volatility_expansion`` is the short-window
    volatility divided by its baseline, ``liquidity_stress`` is a 0..100 stress
    proxy, and ``limit_down_pressure`` can represent either a boolean limit-down
    event or a 0..100 pressure proxy.
    """

    short_window_return_pct: float = 0.0
    drawdown_velocity_pct: float = 0.0
    volatility_expansion: float = 1.0
    liquidity_stress: float = 0.0
    limit_down_pressure: float | bool = False


@dataclass(frozen=True)
class CrashAccelerationResult:
    """CAL result used only as an acute-crash floor, never as a bear detector."""

    score: int
    floor_signal: SignalColor | None
    conditions: Mapping[str, bool]

    @property
    def cal_score(self) -> int:
        """Alias used by audit output and callers that name the layer explicitly."""

        return self.score

    def as_dict(self) -> dict[str, Any]:
        return {
            "cal_score": self.score,
            "floor_signal": self.floor_signal,
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


def score_crash_acceleration_layer(data: CrashAccelerationInput) -> CrashAccelerationResult:
    """Score CAL as an acute-crash override, not a slow bear-market detector.

    CAL remains dormant unless there is short-window downside acceleration,
    crash-like drawdown velocity, or limit-down pressure. Volatility expansion
    and liquidity stress can strengthen an acute signal but cannot activate CAL
    by themselves. This keeps gradual bear-market deterioration at
    ``cal_score=0`` and ``floor_signal=None``.
    """

    limit_down_pressure_value = _pressure_value(data.limit_down_pressure)
    conditions = {
        "short_window_downside_acceleration": data.short_window_return_pct <= -4.0,
        "crash_like_drawdown_velocity": data.drawdown_velocity_pct <= -5.0,
        "volatility_expansion": data.volatility_expansion >= 1.75,
        "liquidity_stress": data.liquidity_stress >= 70.0,
        "limit_down_pressure": limit_down_pressure_value >= 80.0,
    }
    acute_velocity_present = (
        conditions["short_window_downside_acceleration"]
        or conditions["crash_like_drawdown_velocity"]
        or conditions["limit_down_pressure"]
    )
    if not acute_velocity_present:
        return CrashAccelerationResult(score=0, floor_signal=None, conditions=conditions)

    score = sum(conditions.values())
    floor: SignalColor | None
    if score >= 4 or (conditions["limit_down_pressure"] and score >= 3):
        floor = "Red"
    elif score >= 2:
        floor = "Orange"
    else:
        floor = None
    return CrashAccelerationResult(score=score, floor_signal=floor, conditions=conditions)


def apply_signal_floor(signal: SignalColor, floor_signal: SignalColor | None) -> SignalColor:
    """Raise ``signal`` to ``floor_signal`` when the floor is more conservative."""

    if floor_signal is None or _SIGNAL_RANK[signal] >= _SIGNAL_RANK[floor_signal]:
        return signal
    return floor_signal


def resolve_five_light_signal(
    data: DecisionMatrixInput,
    bear_trend: BearTrendResult | None = None,
    cal: CrashAccelerationResult | None = None,
) -> DecisionMatrixResult:
    """Apply V5.1.4 rules, then non-downgrading bear/CAL floors."""

    bcd_status_complete = str(data.bcd_status).upper() == "COMPLETE"
    effective_bcd = data.bcd if bcd_status_complete else None

    trace = {
        "tcwrs": data.tcwrs,
        "eti5_total": data.eti5_total,
        "eti_available_count": data.eti_available_count,
        "tail_risk": data.tail_risk,
        "bcd": effective_bcd,
        "bcd_status": data.bcd_status,
        "taiex": data.taiex,
        "ma20": data.ma20,
        "consecutive_down_days": data.consecutive_down_days,
        "mhs": data.mhs,
        "cp_score": data.cp_score,
        "cp_red_confirmation": data.cp_score is not None and data.cp_score >= 55,
        "bear_trend": bear_trend.as_dict() if bear_trend is not None else None,
        "cal": cal.as_dict() if cal is not None else None,
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
            return _with_floor("Red", rule, trace, bear_trend, cal)

    orange_rules = (
        (61 <= data.tcwrs <= 75 and data.eti5_total >= 2, "61 <= TCWRS <= 75 AND ETI5_total >= 2"),
        (data.eti5_total >= 3 and data.tcwrs >= 41, "ETI5_total >= 3 AND TCWRS >= 41"),
        (data.tcwrs >= 41 and data.tail_risk >= 61 and data.eti5_total >= 2, "TCWRS >= 41 AND TailRisk >= 61 AND ETI5_total >= 2"),
        (effective_bcd is not None and effective_bcd >= 61 and data.tcwrs >= 41 and data.eti5_total >= 2, "BCD >= 61 AND TCWRS >= 41 AND ETI5_total >= 2"),
        (data.eti5_total >= 4 and data.tcwrs < 41, "ETI5_total >= 4 AND TCWRS < 41; downgraded to Orange"),
    )
    for matched, rule in orange_rules:
        if matched:
            trace["red_confirmed_by"] = None
            return _with_floor("Orange", rule, trace, bear_trend, cal)

    strengthened_yellow_rules = (
        (41 <= data.tcwrs <= 60, "41 <= TCWRS <= 60"),
        (data.mhs >= 86 and data.tcwrs >= 30, "MHS >= 86 AND TCWRS >= 30"),
        (data.eti5_total >= 2 and data.tcwrs >= 21, "ETI5_total >= 2 AND TCWRS >= 21"),
        (data.tail_risk >= 61 and data.tcwrs >= 21, "TailRisk >= 61 AND TCWRS >= 21"),
        (effective_bcd is not None and effective_bcd >= 61 and data.tcwrs >= 21, "BCD >= 61 AND TCWRS >= 21"),
    )
    for matched, rule in strengthened_yellow_rules:
        if matched:
            trace["red_confirmed_by"] = None
            return _with_floor("Strengthened Yellow", rule, trace, bear_trend, cal)

    yellow_rules = (
        (21 <= data.tcwrs <= 40, "21 <= TCWRS <= 40"),
        (data.mhs >= 71, "MHS >= 71"),
        (data.eti5_total >= 1, "ETI5_total >= 1"),
        (data.tail_risk >= 41, "TailRisk >= 41"),
        (effective_bcd is not None and effective_bcd >= 41, "BCD >= 41"),
    )
    for matched, rule in yellow_rules:
        if matched:
            trace["red_confirmed_by"] = None
            return _with_floor("Yellow", rule, trace, bear_trend, cal)

    trace["red_confirmed_by"] = None
    return _with_floor("Green", "Default/green light conditions", trace, bear_trend, cal)


def _append_cp_confirmation(confirmed_by: str, cp_score: float | None) -> str:
    if cp_score is not None and cp_score >= 55:
        return f"{confirmed_by}+CP>=55"
    return confirmed_by


def _with_floor(
    signal: SignalColor,
    rule: str,
    trace: dict[str, Any],
    bear_trend: BearTrendResult | None,
    cal: CrashAccelerationResult | None,
) -> DecisionMatrixResult:
    bear_floor_signal = bear_trend.floor_signal if bear_trend is not None else None
    signal_after_bear = apply_signal_floor(signal, bear_floor_signal)

    cal_floor_signal = cal.floor_signal if cal is not None else None
    signal_after_cal = apply_signal_floor(signal_after_bear, cal_floor_signal)

    resolved_rule = rule
    rule_suffixes = []
    if signal_after_bear != signal:
        rule_suffixes.append(f"Bear Trend Filter floor -> {signal_after_bear}")
    if signal_after_cal != signal_after_bear:
        rule_suffixes.append(f"CAL acute-crash floor -> {signal_after_cal}")
    if rule_suffixes:
        resolved_rule = f"{rule}; {'; '.join(rule_suffixes)}"

    resolved_trace = dict(trace)
    resolved_trace["signal_before_bear_trend_floor"] = signal
    resolved_trace["signal_after_bear_trend_floor"] = signal_after_bear
    resolved_trace["signal_before_cal"] = signal_after_bear
    resolved_trace["signal_after_cal"] = signal_after_cal
    return _result(signal_after_cal, _EXPOSURE_LIMITS[signal_after_cal], resolved_rule, resolved_trace)


def _pressure_value(value: float | bool) -> float:
    if isinstance(value, bool):
        return 100.0 if value else 0.0
    return float(value)


def _result(signal: SignalColor, exposure: str, rule: str, trace: Mapping[str, Any]) -> DecisionMatrixResult:
    return DecisionMatrixResult(
        signal=signal,
        equity_exposure_limit=exposure,
        matched_rule=rule,
        trace_output=trace,
    )
