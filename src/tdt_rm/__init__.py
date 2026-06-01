"""Public package API for TDT-RM scoring modules."""

from .backtest import (
    BacktestConfig,
    BacktestMetrics,
    BacktestResult,
    BacktestSignal,
    HistoricalBacktestObservation,
    run_historical_backtest,
)
from .crash_probability import (
    CrashProbabilityInput,
    CrashProbabilityResult,
    cp_level_for_score,
    score_crash_probability,
)
from .eti5 import ETI5Input, ETI5Result, ETI5SignalResult, score_eti5
from .tcwrs import (
    TCWRSFactorResult,
    TCWRSInput,
    TCWRSResult,
    score_b,
    score_f,
    score_g,
    score_l,
    score_m,
    score_p,
    score_tcwrs,
    score_v,
    score_x,
)

__all__ = [
    "BacktestConfig",
    "BacktestMetrics",
    "BacktestResult",
    "BacktestSignal",
    "HistoricalBacktestObservation",
    "run_historical_backtest",
    "CrashProbabilityInput",
    "CrashProbabilityResult",
    "cp_level_for_score",
    "score_crash_probability",
    "ETI5Input",
    "ETI5Result",
    "ETI5SignalResult",
    "score_eti5",
    "TCWRSFactorResult",
    "TCWRSInput",
    "TCWRSResult",
    "score_b",
    "score_f",
    "score_g",
    "score_l",
    "score_m",
    "score_p",
    "score_tcwrs",
    "score_v",
    "score_x",
]
