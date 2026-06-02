"""ETI-5 module for TDT-RM V5.1.4 Backtest Calibration Patch.

ETI-5 (Exit Trigger Index 5) is the binary landing-confirmation layer for
five TCWRS-adjacent damage signals.  TCWRS measures damage severity; ETI-5
measures how many distinct damage signals have landed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Collection

TraceOutput = dict[str, Any]


@dataclass(frozen=True)
class ETI5Input:
    """Inputs required to compute the five ETI-5 binary components.

    Numeric percentage inputs use percentage points, not decimals.  For example,
    a 0.6% three-day USD/TWD rise is represented as ``0.6``.

    Some predicates in the frozen specification are intentionally accepted as
    explicit booleans because their upstream raw-data definitions can vary by
    data vendor (for example, a "large" foreign sell or breadth weakness).
    """

    # ETI-1: Index below 20MA.
    close: float
    ma20: float
    close_not_back_above_ma20_for_2_days: bool = False

    # ETI-2: Foreign selling.
    foreign_spot_net_sell_consecutive_days: int = 0
    foreign_large_sell: bool = False
    futures_hedging_increases: bool = False

    # ETI-3: TWD depreciation, represented by USD/TWD appreciation.
    usd_twd_3d_change_pct: float = 0.0
    usd_twd_5d_change_pct: float = 0.0

    # ETI-4: Breadth deterioration.
    index_down: bool = False
    declining_issues_significantly_gt_advancing: bool = False
    breadth_weakens_for_2_days: bool = False

    # ETI-5: Leadership breakdown.
    count_main_7_below_ma20: int = 0

    # V5.1.4 availability calibration. Use ETI-1..ETI-5 codes.
    # None preserves legacy behavior (all components available). Backtests with
    # price-only tapes should usually pass {"ETI-1"} instead of proxying every
    # ETI component from the index price sequence.
    available_components: Collection[str] | None = None


@dataclass(frozen=True)
class ETI5SignalResult:
    """Auditable result for one ETI-5 binary component."""

    code: str
    name: str
    triggered: bool
    available: bool
    matched_rule: str
    conditions: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        """Return a serializable signal trace."""

        trace_output = dict(self.conditions)
        return {
            "code": self.code,
            "name": self.name,
            "triggered": self.triggered,
            "available": self.available,
            "score": int(self.triggered),
            "matched_rule": self.matched_rule,
            "conditions": trace_output,
            "trace_output": trace_output,
        }


@dataclass(frozen=True)
class ETI5Result:
    """Aggregate ETI-5 result with requested score, triggers, and trace output."""

    signals: Mapping[str, ETI5SignalResult]

    @property
    def eti_available_count(self) -> int:
        """Return the count of ETI components with available source data."""

        return sum(int(signal.available) for signal in self.signals.values())

    @property
    def eti_raw_score(self) -> int:
        """Return the effective raw score across available components before caps."""

        return sum(int(signal.triggered) for signal in self.signals.values() if signal.available)

    @property
    def eti_cap_reason(self) -> str | None:
        """Explain the V5.1.4 data-availability cap, when any."""

        count = self.eti_available_count
        if count <= 2:
            return "available components <= 2; capped at 2"
        if count == 3:
            return "available components = 3; capped at 3"
        return None

    @property
    def eti_capped_score(self) -> int:
        """Return ETI-5 after V5.1.4 availability caps."""

        count = self.eti_available_count
        if count <= 2:
            return min(self.eti_raw_score, 2)
        if count == 3:
            return min(self.eti_raw_score, 3)
        return self.eti_raw_score

    @property
    def eti_score(self) -> int:
        """Return ETI-5 total score in the inclusive range 0-5."""

        return self.eti_capped_score

    @property
    def eti5_total(self) -> int:
        """Compatibility alias for the frozen specification's ETI5_total name."""

        return self.eti_score

    @property
    def triggered_signals(self) -> list[str]:
        """Return component codes for all triggered ETI-5 signals."""

        return [code for code, signal in self.signals.items() if signal.available and signal.triggered]

    @property
    def trace_output(self) -> dict[str, dict[str, Any]]:
        """Return each ETI-5 component's auditable trace keyed by component code."""

        return {code: signal.as_dict() for code, signal in self.signals.items()}

    def as_dict(self) -> dict[str, Any]:
        """Return a serializable dict preserving all ETI-5 traces."""

        return {
            "eti_score": self.eti_score,
            "eti_available_count": self.eti_available_count,
            "eti_raw_score": self.eti_raw_score,
            "eti_capped_score": self.eti_capped_score,
            "eti_cap_reason": self.eti_cap_reason,
            "triggered_signals": self.triggered_signals,
            "trace_output": self.trace_output,
            # Compatibility alias for the specification term.
            "eti5_total": self.eti5_total,
        }


def _signal(
    code: str,
    name: str,
    triggered: bool,
    available: bool,
    triggered_rule: str,
    default_rule: str,
    conditions: TraceOutput,
) -> ETI5SignalResult:
    return ETI5SignalResult(
        code=code,
        name=name,
        triggered=triggered and available,
        available=available,
        matched_rule=(triggered_rule if triggered else default_rule) if available else "component unavailable; not scored",
        conditions=conditions,
    )


def score_eti5(data: ETI5Input) -> ETI5Result:
    """Score ETI-5 with V5.1.4 data-availability caps and full trace."""

    available_components = (
        {"ETI-1", "ETI-2", "ETI-3", "ETI-4", "ETI-5"}
        if data.available_components is None
        else set(data.available_components)
    )

    eti_1_conditions: TraceOutput = {
        "close_lt_ma20": data.close < data.ma20,
        "close_not_back_above_ma20_for_2_days": data.close_not_back_above_ma20_for_2_days,
        "raw": {
            "close": data.close,
            "ma20": data.ma20,
            "close_not_back_above_ma20_for_2_days": data.close_not_back_above_ma20_for_2_days,
        },
    }
    eti_1 = _signal(
        "ETI-1",
        "Index below 20MA",
        eti_1_conditions["close_lt_ma20"]
        or eti_1_conditions["close_not_back_above_ma20_for_2_days"],
        "ETI-1" in available_components,
        "close < MA20 OR close_not_back_above_MA20_for_2_days",
        "index remains above/effectively back above MA20",
        eti_1_conditions,
    )

    eti_2_conditions: TraceOutput = {
        "foreign_spot_net_sell_for_2_days": data.foreign_spot_net_sell_consecutive_days
        >= 2,
        "foreign_large_sell_and_futures_hedging_increases": data.foreign_large_sell
        and data.futures_hedging_increases,
        "raw": {
            "foreign_spot_net_sell_consecutive_days": data.foreign_spot_net_sell_consecutive_days,
            "foreign_large_sell": data.foreign_large_sell,
            "futures_hedging_increases": data.futures_hedging_increases,
        },
    }
    eti_2 = _signal(
        "ETI-2",
        "Foreign selling",
        eti_2_conditions["foreign_spot_net_sell_for_2_days"]
        or eti_2_conditions["foreign_large_sell_and_futures_hedging_increases"],
        "ETI-2" in available_components,
        "foreign_spot_net_sell_for_2_days OR (foreign_large_sell AND futures_hedging_increases)",
        "foreign selling confirmation not triggered",
        eti_2_conditions,
    )

    eti_3_conditions: TraceOutput = {
        "usd_twd_3d_change_gt_0_5": data.usd_twd_3d_change_pct > 0.5,
        "usd_twd_5d_change_gt_1_0": data.usd_twd_5d_change_pct > 1.0,
        "raw": {
            "usd_twd_3d_change_pct": data.usd_twd_3d_change_pct,
            "usd_twd_5d_change_pct": data.usd_twd_5d_change_pct,
        },
    }
    eti_3 = _signal(
        "ETI-3",
        "TWD depreciation",
        eti_3_conditions["usd_twd_3d_change_gt_0_5"]
        or eti_3_conditions["usd_twd_5d_change_gt_1_0"],
        "ETI-3" in available_components,
        "USD_TWD_3d_change > 0.5% OR USD_TWD_5d_change > 1.0%",
        "TWD depreciation confirmation not triggered",
        eti_3_conditions,
    )

    eti_4_conditions: TraceOutput = {
        "index_down_and_declining_issues_significantly_gt_advancing": data.index_down
        and data.declining_issues_significantly_gt_advancing,
        "breadth_weakens_for_2_days": data.breadth_weakens_for_2_days,
        "raw": {
            "index_down": data.index_down,
            "declining_issues_significantly_gt_advancing": data.declining_issues_significantly_gt_advancing,
            "breadth_weakens_for_2_days": data.breadth_weakens_for_2_days,
        },
    }
    eti_4 = _signal(
        "ETI-4",
        "Breadth deterioration",
        eti_4_conditions["index_down_and_declining_issues_significantly_gt_advancing"]
        or eti_4_conditions["breadth_weakens_for_2_days"],
        "ETI-4" in available_components,
        "(index_down AND declining_issues >> advancing_issues) OR breadth_weakens_for_2_days",
        "breadth deterioration confirmation not triggered",
        eti_4_conditions,
    )

    eti_5_conditions: TraceOutput = {
        "count_main_7_below_ma20_gte_4": data.count_main_7_below_ma20 >= 4,
        "count_main_7_below_ma20_gte_5_high_risk_confirmation": data.count_main_7_below_ma20
        >= 5,
        "raw": {
            "count_main_7_below_ma20": data.count_main_7_below_ma20,
        },
    }
    eti_5 = _signal(
        "ETI-5",
        "Leadership breakdown",
        eti_5_conditions["count_main_7_below_ma20_gte_4"],
        "ETI-5" in available_components,
        "count_main_7_below_MA20 >= 4",
        "leadership breakdown confirmation not triggered",
        eti_5_conditions,
    )

    signals = {signal.code: signal for signal in (eti_1, eti_2, eti_3, eti_4, eti_5)}
    result = ETI5Result(signals=signals)
    if result.eti_score < 0 or result.eti_score > 5:
        raise ValueError(f"ETI-5 score {result.eti_score} outside 0-5")
    return result
