from datetime import date

import pytest

from tdt_rm import PerformanceObservation, generate_performance_report


def test_generate_performance_report_compares_buy_hold_and_signals_without_lookahead():
    observations = [
        PerformanceObservation(date(2022, 1, 3), 100, "Green"),
        PerformanceObservation(date(2022, 1, 4), 90, "Red"),
        PerformanceObservation(date(2022, 1, 5), 80, "Red"),
        PerformanceObservation(date(2022, 1, 6), 88, "Green"),
    ]

    report = generate_performance_report(observations)

    buy_hold, signals = report.strategies
    assert buy_hold.strategy == "Buy and Hold"
    assert buy_hold.total_return == pytest.approx(-0.12)
    assert buy_hold.max_drawdown == pytest.approx(-0.2)
    assert buy_hold.signal_count == 0

    assert signals.strategy == "TDT-RM Signals"
    assert signals.total_return == pytest.approx(-0.1)
    assert signals.max_drawdown == pytest.approx(-0.1)
    assert signals.signal_count == 2
    assert signals.exposure_days == 1

    markdown = report.to_markdown()
    assert "| Buy and Hold |" in markdown
    assert "| TDT-RM Signals |" in markdown
    assert "Signal Count" in markdown


def test_generate_performance_report_requires_two_observations():
    with pytest.raises(ValueError, match="at least two observations"):
        generate_performance_report([PerformanceObservation(date(2022, 1, 3), 100, "Green")])
