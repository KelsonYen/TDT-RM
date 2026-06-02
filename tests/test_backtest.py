import pytest

from tdt_rm import (
    BacktestConfig,
    ETI5Input,
    HistoricalBacktestObservation,
    TCWRSInput,
    run_historical_backtest,
)


def _tcwrs_high_risk() -> TCWRSInput:
    return TCWRSInput(
        close=80,
        ma5=90,
        ma20=95,
        ma60=100,
        ma20_slope=-1,
        one_day_return_pct=-4,
        turnover_amount=200,
        ma20_turnover=100,
        turnover_top_10pct_1y=True,
        long_black_candle=True,
        close_is_black=True,
        foreign_spot_net_sell_consecutive_days=3,
        futures_net_short_increases=True,
        foreign_spot_large_sell=True,
        pcr_rises=True,
        usd_twd_5d_change_pct=1.2,
        index_down=True,
        twd_depreciates_significantly=True,
        foreign_spot_net_sell=True,
        index_5d_return_pct=-3.5,
        margin_balance_5d_decline_pct=0.2,
        margin_not_retreating=True,
        declining_issues_significantly_expand=True,
        declining_issues_significantly_gt_advancing=True,
        count_main_7_below_ma20=4,
        count_main_7_below_ma60=2,
        sox=80,
        sox_ma20=90,
        sox_ma60=100,
        nasdaq=80,
        nasdaq_ma20=90,
        vix_spikes=True,
    )


def _tcwrs_low_risk() -> TCWRSInput:
    return TCWRSInput(
        close=110,
        ma5=105,
        ma20=100,
        ma60=95,
        ma20_slope=1,
        volume_up=True,
        price_up=True,
        close_is_red=True,
        foreign_spot_net_buy=1,
        futures_net_short_decreases=True,
        pcr_stable=True,
        vix_stable=True,
        twd_appreciates=True,
        margin_balance_5d_flat_or_down=True,
        index_up_or_flat=True,
        advancing_issues=600,
        declining_issues=300,
        majority_main_7_assets_above_ma20=True,
        us_stocks_stable=True,
        sox_stable=True,
        vix_stable_global=True,
        sox=110,
        sox_ma20=100,
        sox_ma60=95,
        nasdaq=110,
        nasdaq_ma20=100,
    )


def _eti_high_risk() -> ETI5Input:
    return ETI5Input(
        close=80,
        ma20=95,
        foreign_spot_net_sell_consecutive_days=2,
        usd_twd_3d_change_pct=0.6,
        index_down=True,
        declining_issues_significantly_gt_advancing=True,
        count_main_7_below_ma20=4,
    )


def _eti_low_risk() -> ETI5Input:
    return ETI5Input(close=110, ma20=100)


def test_historical_backtest_scores_rows_and_matches_forward_events():
    observations = [
        HistoricalBacktestObservation("2026-01-01", _tcwrs_high_risk(), _eti_high_risk(), 70, 70),
        HistoricalBacktestObservation("2026-01-02", _tcwrs_low_risk(), _eti_low_risk(), 0, 0),
        HistoricalBacktestObservation("2026-01-03", _tcwrs_low_risk(), _eti_low_risk(), 0, 0, realized_event=True),
        HistoricalBacktestObservation("2026-01-04", _tcwrs_high_risk(), _eti_high_risk(), 70, 70),
    ]

    result = run_historical_backtest(
        observations,
        BacktestConfig(forward_window=2, signal_mode="cp", cp_threshold=56),
    )

    assert [signal.observed_at.isoformat() for signal in result.signals] == [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
        "2026-01-04",
    ]
    assert result.signals[0].signal_triggered is True
    assert result.signals[0].event_within_window is True
    assert result.signals[0].days_to_event == 2
    assert result.signals[1].signal_triggered is False
    assert result.signals[1].event_within_window is True
    assert result.signals[3].signal_triggered is True
    assert result.signals[3].event_within_window is False
    assert result.metrics.true_positives == 1
    assert result.metrics.false_positives == 1
    assert result.metrics.false_negatives == 1
    assert result.metrics.precision == 0.5
    assert result.metrics.recall == 0.5
    assert result.metrics.average_lead_days == 2

    serialized = result.as_dict()
    assert serialized["config"]["signal_mode"] == "cp"
    assert serialized["signals"][0]["trace_output"]["tcwrs"]["total_score"] > 55
    assert serialized["signals"][0]["trace_output"]["crash_probability"]["cp_score"] >= 56


def test_backtest_any_mode_uses_available_tcwrs_when_optional_modules_absent():
    result = run_historical_backtest(
        [HistoricalBacktestObservation("2026-01-01", _tcwrs_high_risk())],
        BacktestConfig(signal_mode="any", tcwrs_threshold=55),
    )

    assert result.signals[0].signal_triggered is True
    assert result.signals[0].eti5_score is None
    assert result.signals[0].cp_score is None


def test_backtest_rejects_signal_mode_without_required_inputs():
    with pytest.raises(ValueError, match="signal_mode='cp'"):
        run_historical_backtest(
            [HistoricalBacktestObservation("2026-01-01", _tcwrs_high_risk())],
            BacktestConfig(signal_mode="cp"),
        )


def test_backtest_can_include_same_day_events():
    observations = [
        HistoricalBacktestObservation("2026-01-01", _tcwrs_high_risk(), realized_event=True)
    ]

    excluded = run_historical_backtest(
        observations,
        BacktestConfig(forward_window=0, include_same_day_event=False),
    )
    included = run_historical_backtest(
        observations,
        BacktestConfig(forward_window=0, include_same_day_event=True),
    )

    assert excluded.signals[0].event_within_window is False
    assert included.signals[0].event_within_window is True
    assert included.signals[0].days_to_event == 0


def test_backtest_serializes_v514_eti_availability_fields():
    result = run_historical_backtest(
        [
            HistoricalBacktestObservation(
                "2026-01-01",
                _tcwrs_high_risk(),
                ETI5Input(close=80, ma20=95, available_components={"ETI-1"}),
                70,
                70,
            )
        ],
        BacktestConfig(signal_mode="eti5", eti5_threshold=1),
    )

    row = result.as_dict()["signals"][0]
    assert row["eti_available_count"] == 1
    assert row["eti_raw_score"] == 1
    assert row["eti_capped_score"] == 1
    assert row["eti_cap_reason"] == "available components <= 2; capped at 2"
