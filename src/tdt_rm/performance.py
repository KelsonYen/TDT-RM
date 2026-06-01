"""Performance reporting utilities for TDT-RM signal backtests.

The report compares a fully invested buy-and-hold baseline against a simple
TDT-RM signal strategy that exits risk exposure after risk-off signals.  Signal
exposure is applied to the next available return so the calculation does not
benefit from same-day lookahead.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping, Sequence

TRADING_DAYS_PER_YEAR = 252
DEFAULT_RISK_OFF_SIGNALS = frozenset({"Red", "Orange"})


@dataclass(frozen=True)
class PerformanceObservation:
    """Daily close and TDT-RM signal used in a performance comparison."""

    observed_at: date
    close: float
    signal: str


@dataclass(frozen=True)
class StrategyPerformance:
    """Aggregate return/risk metrics for one strategy."""

    strategy: str
    cagr: float | None
    max_drawdown: float
    sharpe_ratio: float | None
    signal_count: int
    total_return: float
    observations: int
    exposure_days: int

    def as_dict(self) -> dict[str, float | int | str | None]:
        """Return a JSON-serializable metric summary."""

        return {
            "strategy": self.strategy,
            "cagr": self.cagr,
            "max_drawdown": self.max_drawdown,
            "sharpe_ratio": self.sharpe_ratio,
            "signal_count": self.signal_count,
            "total_return": self.total_return,
            "observations": self.observations,
            "exposure_days": self.exposure_days,
        }


@dataclass(frozen=True)
class PerformanceReport:
    """Buy-and-hold versus TDT-RM signal performance report."""

    period_start: date
    period_end: date
    risk_off_signals: Sequence[str]
    strategies: Sequence[StrategyPerformance]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable report."""

        return {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "risk_off_signals": list(self.risk_off_signals),
            "strategies": [strategy.as_dict() for strategy in self.strategies],
        }

    def to_markdown(self) -> str:
        """Render the report as a Markdown table."""

        lines = [
            "# TDT-RM Performance Report",
            "",
            f"Period: {self.period_start.isoformat()} to {self.period_end.isoformat()}",
            f"Risk-off signals: {', '.join(self.risk_off_signals)}",
            "",
            "| Strategy | CAGR | Max Drawdown | Sharpe Ratio | Signal Count |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for strategy in self.strategies:
            lines.append(
                "| "
                f"{strategy.strategy} | "
                f"{_format_percent(strategy.cagr)} | "
                f"{_format_percent(strategy.max_drawdown)} | "
                f"{_format_number(strategy.sharpe_ratio)} | "
                f"{strategy.signal_count} |"
            )
        lines.extend(
            [
                "",
                "Notes:",
                "- TDT-RM Signals uses next-session execution: today's signal controls exposure to the next observed return.",
                "- Red and Orange are treated as risk-off by default; risk-off days earn a 0% cash return.",
                "- Sharpe Ratio is annualized with 252 trading days and a 0% risk-free rate.",
            ]
        )
        return "\n".join(lines) + "\n"


def load_performance_observations_csv(
    path: str | Path,
    *,
    date_column: str = "Date",
    close_column: str = "Close",
    signal_column: str = "Signal",
) -> list[PerformanceObservation]:
    """Load date, close, and signal columns from a backtest CSV."""

    observations: list[PerformanceObservation] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            observations.append(
                PerformanceObservation(
                    observed_at=date.fromisoformat(_required(row, date_column)),
                    close=float(_required(row, close_column)),
                    signal=_required(row, signal_column),
                )
            )
    return observations


def generate_performance_report(
    observations: Iterable[PerformanceObservation],
    *,
    risk_off_signals: Iterable[str] = DEFAULT_RISK_OFF_SIGNALS,
) -> PerformanceReport:
    """Compare buy-and-hold and next-session TDT-RM signal performance."""

    ordered = sorted(observations, key=lambda observation: observation.observed_at)
    if len(ordered) < 2:
        raise ValueError("at least two observations are required")
    if any(observation.close <= 0 for observation in ordered):
        raise ValueError("close values must be positive")

    risk_off = frozenset(risk_off_signals)
    daily_returns = _daily_returns(ordered)
    tdt_returns = [
        0.0 if previous.signal in risk_off else daily_return
        for previous, daily_return in zip(ordered[:-1], daily_returns)
    ]
    signal_count = sum(observation.signal in risk_off for observation in ordered)
    exposure_days = sum(observation.signal not in risk_off for observation in ordered[:-1])

    return PerformanceReport(
        period_start=ordered[0].observed_at,
        period_end=ordered[-1].observed_at,
        risk_off_signals=tuple(sorted(risk_off)),
        strategies=(
            _calculate_strategy_performance(
                strategy="Buy and Hold",
                returns=daily_returns,
                signal_count=0,
                observations=len(ordered),
                exposure_days=len(daily_returns),
            ),
            _calculate_strategy_performance(
                strategy="TDT-RM Signals",
                returns=tdt_returns,
                signal_count=signal_count,
                observations=len(ordered),
                exposure_days=exposure_days,
            ),
        ),
    )


def _daily_returns(observations: Sequence[PerformanceObservation]) -> list[float]:
    return [
        current.close / previous.close - 1.0
        for previous, current in zip(observations[:-1], observations[1:])
    ]


def _calculate_strategy_performance(
    *,
    strategy: str,
    returns: Sequence[float],
    signal_count: int,
    observations: int,
    exposure_days: int,
) -> StrategyPerformance:
    equity_curve = _equity_curve(returns)
    total_return = equity_curve[-1] - 1.0
    years = len(returns) / TRADING_DAYS_PER_YEAR
    cagr = (equity_curve[-1] ** (1 / years) - 1.0) if years > 0 and equity_curve[-1] > 0 else None
    return StrategyPerformance(
        strategy=strategy,
        cagr=cagr,
        max_drawdown=_max_drawdown(equity_curve),
        sharpe_ratio=_sharpe_ratio(returns),
        signal_count=signal_count,
        total_return=total_return,
        observations=observations,
        exposure_days=exposure_days,
    )


def _equity_curve(returns: Sequence[float]) -> list[float]:
    equity = [1.0]
    for daily_return in returns:
        equity.append(equity[-1] * (1.0 + daily_return))
    return equity


def _max_drawdown(equity_curve: Sequence[float]) -> float:
    peak = equity_curve[0]
    max_drawdown = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        drawdown = equity / peak - 1.0
        max_drawdown = min(max_drawdown, drawdown)
    return max_drawdown


def _sharpe_ratio(returns: Sequence[float]) -> float | None:
    if not returns:
        return None
    mean_return = sum(returns) / len(returns)
    variance = sum((daily_return - mean_return) ** 2 for daily_return in returns) / len(returns)
    volatility = math.sqrt(variance)
    if volatility == 0:
        return None
    return mean_return / volatility * math.sqrt(TRADING_DAYS_PER_YEAR)


def _required(row: Mapping[str, str], column: str) -> str:
    value = row.get(column)
    if value is None or value == "":
        raise ValueError(f"Missing required column value: {column}")
    return value


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def _format_number(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"
