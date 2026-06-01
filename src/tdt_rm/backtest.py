"""Historical backtest framework for TDT-RM scoring modules.

The framework intentionally stays dependency-free so it can run in the same
minimal environments as the scoring modules.  A backtest row is an auditable
snapshot of inputs available on a historical date plus an optional realized
future event label.  The runner scores each row, applies a configurable signal
rule, then evaluates whether a labeled event occurs inside the configured
forward window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Literal, Mapping, Sequence

from .crash_probability import CrashProbabilityInput, score_crash_probability
from .eti5 import ETI5Input, score_eti5
from .tcwrs import TCWRSInput, score_tcwrs

TraceOutput = dict[str, Any]
SignalMode = Literal["any", "all", "cp", "tcwrs", "eti5"]


@dataclass(frozen=True)
class HistoricalBacktestObservation:
    """One historical observation to be scored and later evaluated.

    ``observed_at`` accepts either a ``date`` or an ISO ``YYYY-MM-DD`` string.
    ``tcwrs_input`` is required because TCWRS is the core risk score.  ETI-5 and
    Crash Probability can be included by providing ``eti5_input`` plus
    ``tail_risk`` and ``bcd``.  ``realized_event`` should be true on dates where
    the outcome being tested occurred, for example a crash or drawdown breach.
    """

    observed_at: date | str
    tcwrs_input: TCWRSInput
    eti5_input: ETI5Input | None = None
    tail_risk: float | None = None
    bcd: float | None = None
    realized_event: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BacktestConfig:
    """Configuration for historical signal generation and event matching."""

    forward_window: int = 20
    signal_mode: SignalMode = "any"
    tcwrs_threshold: float = 55
    eti5_threshold: float = 3
    cp_threshold: float = 56
    include_same_day_event: bool = False

    def __post_init__(self) -> None:
        if self.forward_window < 0:
            raise ValueError("forward_window must be >= 0")
        if self.signal_mode not in {"any", "all", "cp", "tcwrs", "eti5"}:
            raise ValueError(f"Unsupported signal_mode: {self.signal_mode}")


@dataclass(frozen=True)
class BacktestSignal:
    """Per-observation score, signal decision, and forward-event label."""

    observed_at: date
    tcwrs_score: int
    tcwrs_triggered: bool
    eti5_score: int | None
    eti5_triggered: bool | None
    cp_score: float | None
    cp_level: str | None
    cp_triggered: bool | None
    signal_triggered: bool
    realized_event: bool
    event_within_window: bool
    days_to_event: int | None
    trace_output: TraceOutput
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a serializable signal row with full scoring trace."""

        return {
            "observed_at": self.observed_at.isoformat(),
            "tcwrs_score": self.tcwrs_score,
            "tcwrs_triggered": self.tcwrs_triggered,
            "eti5_score": self.eti5_score,
            "eti5_triggered": self.eti5_triggered,
            "cp_score": self.cp_score,
            "cp_level": self.cp_level,
            "cp_triggered": self.cp_triggered,
            "signal_triggered": self.signal_triggered,
            "realized_event": self.realized_event,
            "event_within_window": self.event_within_window,
            "days_to_event": self.days_to_event,
            "trace_output": self.trace_output,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class BacktestMetrics:
    """Aggregate binary-classification metrics for a backtest run."""

    observations: int
    signals: int
    events: int
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    precision: float | None
    recall: float | None
    f1: float | None
    hit_rate: float | None
    false_positive_rate: float | None
    average_lead_days: float | None

    def as_dict(self) -> dict[str, Any]:
        """Return a serializable metric summary."""

        return {
            "observations": self.observations,
            "signals": self.signals,
            "events": self.events,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "true_negatives": self.true_negatives,
            "false_negatives": self.false_negatives,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "hit_rate": self.hit_rate,
            "false_positive_rate": self.false_positive_rate,
            "average_lead_days": self.average_lead_days,
        }


@dataclass(frozen=True)
class BacktestResult:
    """Complete historical backtest output."""

    config: BacktestConfig
    signals: Sequence[BacktestSignal]
    metrics: BacktestMetrics

    def as_dict(self) -> dict[str, Any]:
        """Return serializable config, rows, and metrics."""

        return {
            "config": {
                "forward_window": self.config.forward_window,
                "signal_mode": self.config.signal_mode,
                "tcwrs_threshold": self.config.tcwrs_threshold,
                "eti5_threshold": self.config.eti5_threshold,
                "cp_threshold": self.config.cp_threshold,
                "include_same_day_event": self.config.include_same_day_event,
            },
            "signals": [signal.as_dict() for signal in self.signals],
            "metrics": self.metrics.as_dict(),
        }


def run_historical_backtest(
    observations: Iterable[HistoricalBacktestObservation],
    config: BacktestConfig | None = None,
) -> BacktestResult:
    """Score historical observations and evaluate forward event outcomes."""

    resolved_config = config or BacktestConfig()
    sorted_observations = sorted(
        observations,
        key=lambda observation: _coerce_date(observation.observed_at),
    )
    event_indices = [
        index
        for index, observation in enumerate(sorted_observations)
        if observation.realized_event
    ]

    signals = [
        _score_observation(index, observation, event_indices, resolved_config)
        for index, observation in enumerate(sorted_observations)
    ]
    metrics = _calculate_metrics(signals)
    return BacktestResult(config=resolved_config, signals=signals, metrics=metrics)


def _score_observation(
    index: int,
    observation: HistoricalBacktestObservation,
    event_indices: Sequence[int],
    config: BacktestConfig,
) -> BacktestSignal:
    observed_at = _coerce_date(observation.observed_at)
    tcwrs_result = score_tcwrs(observation.tcwrs_input)
    tcwrs_score = tcwrs_result.total_score
    tcwrs_triggered = tcwrs_score >= config.tcwrs_threshold

    eti5_score: int | None = None
    eti5_triggered: bool | None = None
    eti5_trace: dict[str, Any] | None = None
    if observation.eti5_input is not None:
        eti5_result = score_eti5(observation.eti5_input)
        eti5_score = eti5_result.eti_score
        eti5_triggered = eti5_score >= config.eti5_threshold
        eti5_trace = eti5_result.as_dict()

    cp_score: float | None = None
    cp_level: str | None = None
    cp_triggered: bool | None = None
    cp_trace: dict[str, Any] | None = None
    if eti5_score is not None and observation.tail_risk is not None and observation.bcd is not None:
        cp_result = score_crash_probability(
            CrashProbabilityInput(
                tcwrs=tcwrs_score,
                eti5_total=eti5_score,
                tail_risk=observation.tail_risk,
                bcd=observation.bcd,
            )
        )
        cp_score = cp_result.cp_score
        cp_level = cp_result.cp_level
        cp_triggered = cp_score >= config.cp_threshold
        cp_trace = cp_result.as_dict()

    signal_triggered = _resolve_signal_trigger(
        config=config,
        tcwrs_triggered=tcwrs_triggered,
        eti5_triggered=eti5_triggered,
        cp_triggered=cp_triggered,
    )
    days_to_event = _days_to_next_event(
        index=index,
        event_indices=event_indices,
        forward_window=config.forward_window,
        include_same_day_event=config.include_same_day_event,
    )

    return BacktestSignal(
        observed_at=observed_at,
        tcwrs_score=tcwrs_score,
        tcwrs_triggered=tcwrs_triggered,
        eti5_score=eti5_score,
        eti5_triggered=eti5_triggered,
        cp_score=cp_score,
        cp_level=cp_level,
        cp_triggered=cp_triggered,
        signal_triggered=signal_triggered,
        realized_event=observation.realized_event,
        event_within_window=days_to_event is not None,
        days_to_event=days_to_event,
        trace_output={
            "tcwrs": tcwrs_result.as_dict(),
            "eti5": eti5_trace,
            "crash_probability": cp_trace,
            "thresholds": {
                "signal_mode": config.signal_mode,
                "tcwrs_threshold": config.tcwrs_threshold,
                "eti5_threshold": config.eti5_threshold,
                "cp_threshold": config.cp_threshold,
            },
        },
        metadata=observation.metadata,
    )


def _resolve_signal_trigger(
    *,
    config: BacktestConfig,
    tcwrs_triggered: bool,
    eti5_triggered: bool | None,
    cp_triggered: bool | None,
) -> bool:
    available = {
        "tcwrs": tcwrs_triggered,
        "eti5": eti5_triggered,
        "cp": cp_triggered,
    }
    if config.signal_mode in {"tcwrs", "eti5", "cp"}:
        triggered = available[config.signal_mode]
        if triggered is None:
            raise ValueError(f"signal_mode={config.signal_mode!r} requires matching inputs")
        return triggered

    available_values = [value for value in available.values() if value is not None]
    if not available_values:
        return False
    if config.signal_mode == "any":
        return any(available_values)
    return all(available_values)


def _days_to_next_event(
    *,
    index: int,
    event_indices: Sequence[int],
    forward_window: int,
    include_same_day_event: bool,
) -> int | None:
    earliest_distance: int | None = None
    minimum_distance = 0 if include_same_day_event else 1
    for event_index in event_indices:
        distance = event_index - index
        if distance < minimum_distance:
            continue
        if distance > forward_window:
            break
        earliest_distance = distance
        break
    return earliest_distance


def _calculate_metrics(signals: Sequence[BacktestSignal]) -> BacktestMetrics:
    true_positives = sum(
        1 for signal in signals if signal.signal_triggered and signal.event_within_window
    )
    false_positives = sum(
        1 for signal in signals if signal.signal_triggered and not signal.event_within_window
    )
    true_negatives = sum(
        1 for signal in signals if not signal.signal_triggered and not signal.event_within_window
    )
    false_negatives = sum(
        1 for signal in signals if not signal.signal_triggered and signal.event_within_window
    )
    signal_count = true_positives + false_positives
    event_count = true_positives + false_negatives
    precision = _safe_divide(true_positives, signal_count)
    recall = _safe_divide(true_positives, event_count)
    f1 = None
    if precision is not None and recall is not None and precision + recall > 0:
        f1 = 2 * precision * recall / (precision + recall)
    negative_count = false_positives + true_negatives
    lead_days = [
        signal.days_to_event
        for signal in signals
        if signal.signal_triggered and signal.days_to_event is not None
    ]

    return BacktestMetrics(
        observations=len(signals),
        signals=signal_count,
        events=event_count,
        true_positives=true_positives,
        false_positives=false_positives,
        true_negatives=true_negatives,
        false_negatives=false_negatives,
        precision=precision,
        recall=recall,
        f1=f1,
        hit_rate=precision,
        false_positive_rate=_safe_divide(false_positives, negative_count),
        average_lead_days=(sum(lead_days) / len(lead_days) if lead_days else None),
    )


def _safe_divide(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _coerce_date(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)
