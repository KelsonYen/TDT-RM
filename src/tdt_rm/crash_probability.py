"""Crash Probability module for TDT-RM V5.1.3 Rev.3 Final Freeze.

Crash Probability (CP) is the auxiliary aggregate probability layer that blends
TCWRS, ETI-5, TailRisk, and BCD into a capped 0-100 score.  CP is intentionally
kept as a traceable calculation only; signal-upgrade rules live outside this
module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TraceOutput = dict[str, Any]


@dataclass(frozen=True)
class CrashProbabilityInput:
    """Inputs required to compute Crash Probability.

    ``tcwrs`` is the TCWRS total score in points, ``eti5_total`` is the ETI-5
    count in the inclusive range 0-5, and ``tail_risk`` / ``bcd`` are their
    respective 0-100 module scores.
    """

    tcwrs: float
    eti5_total: float
    tail_risk: float
    bcd: float


@dataclass(frozen=True)
class CrashProbabilityResult:
    """Crash Probability aggregate result with requested score, level, and trace."""

    cp_raw: float
    cp_score: float
    cp_level: str
    trace_output: TraceOutput

    def as_dict(self) -> dict[str, Any]:
        """Return a serializable dict preserving the full CP trace."""

        return {
            "cp_score": self.cp_score,
            "cp_level": self.cp_level,
            "trace_output": self.trace_output,
            # Compatibility alias for callers that need the uncapped formula result.
            "cp_raw": self.cp_raw,
        }


def cp_level_for_score(cp_score: float) -> str:
    """Return the Crash Probability tier for a capped CP score."""

    if cp_score < 0 or cp_score > 100:
        raise ValueError(f"CP score {cp_score} outside 0-100")
    if cp_score <= 30:
        return "Low"
    if cp_score <= 55:
        return "Medium"
    if cp_score <= 75:
        return "High"
    return "Extreme"


def score_crash_probability(data: CrashProbabilityInput) -> CrashProbabilityResult:
    """Compute CP = min(CP_raw, 100) and retain every formula contribution."""

    if data.eti5_total < 0 or data.eti5_total > 5:
        raise ValueError(f"ETI5_total {data.eti5_total} outside 0-5")

    tcwrs_contribution = data.tcwrs * 0.40
    eti5_scaled = data.eti5_total * 20
    eti5_contribution = eti5_scaled * 0.30
    tail_risk_contribution = data.tail_risk * 0.20
    bcd_contribution = data.bcd * 0.10
    cp_raw = (
        tcwrs_contribution
        + eti5_contribution
        + tail_risk_contribution
        + bcd_contribution
    )
    cp_score = min(cp_raw, 100)
    cp_level = cp_level_for_score(cp_score)
    trace_output: TraceOutput = {
        "formula": "TCWRS * 0.40 + (ETI5_total * 20) * 0.30 + TailRisk * 0.20 + BCD * 0.10",
        "raw": {
            "tcwrs": data.tcwrs,
            "eti5_total": data.eti5_total,
            "tail_risk": data.tail_risk,
            "bcd": data.bcd,
        },
        "weights": {
            "tcwrs": 0.40,
            "eti5_scaled": 0.30,
            "tail_risk": 0.20,
            "bcd": 0.10,
        },
        "scaled_inputs": {
            "eti5_scaled": eti5_scaled,
        },
        "contributions": {
            "tcwrs": tcwrs_contribution,
            "eti5": eti5_contribution,
            "tail_risk": tail_risk_contribution,
            "bcd": bcd_contribution,
        },
        "cp_raw": cp_raw,
        "cap": 100,
        "cap_applied": cp_score != cp_raw,
        "cp_score": cp_score,
        "cp_level": cp_level,
    }

    return CrashProbabilityResult(
        cp_raw=cp_raw,
        cp_score=cp_score,
        cp_level=cp_level,
        trace_output=trace_output,
    )
