from tdt_rm import (
    BearTrendInput,
    DecisionMatrixInput,
    resolve_five_light_signal,
    score_bear_trend_filter,
)


def test_red_requires_tcwrs_confirmation_for_eti_only_cases():
    high_eti_low_tcwrs = resolve_five_light_signal(
        DecisionMatrixInput(tcwrs=40, eti5_total=4, tail_risk=80, bcd=80, taiex=100, ma20=90, consecutive_down_days=1)
    )
    confirmed = resolve_five_light_signal(
        DecisionMatrixInput(tcwrs=41, eti5_total=4, tail_risk=80, bcd=80, taiex=100, ma20=90, consecutive_down_days=1)
    )

    assert high_eti_low_tcwrs.signal == "Orange"
    assert confirmed.signal == "Red"
    assert confirmed.trace_output["red_confirmed_by"] == "ETI-5+TCWRS"


def test_tcwrs_76_still_triggers_red_and_cp_only_does_not():
    red = resolve_five_light_signal(
        DecisionMatrixInput(tcwrs=76, eti5_total=2, tail_risk=80, bcd=80, taiex=100, ma20=90, consecutive_down_days=1, cp_score=90)
    )
    cp_only = resolve_five_light_signal(
        DecisionMatrixInput(tcwrs=20, eti5_total=0, tail_risk=20, bcd=20, taiex=100, ma20=90, consecutive_down_days=1, cp_score=90)
    )

    assert red.signal == "Red"
    assert red.matched_rule == "TCWRS >= 76"
    assert red.trace_output["red_confirmed_by"] == "TCWRS+CP>=55"
    assert cp_only.signal == "Green"


def test_eti_red_blocked_when_fewer_than_three_components_available():
    result = resolve_five_light_signal(
        DecisionMatrixInput(tcwrs=61, eti5_total=3, tail_risk=80, bcd=80, taiex=100, ma20=90, consecutive_down_days=1, eti_available_count=2)
    )

    assert result.signal == "Orange"
    assert result.matched_rule == "61 <= TCWRS <= 75 AND ETI5_total >= 2"


def test_bcd_orange_uses_calibrated_rule_without_price_confirmation_context():
    result = resolve_five_light_signal(
        DecisionMatrixInput(tcwrs=45, eti5_total=2, tail_risk=20, bcd=80, taiex=80, ma20=90, consecutive_down_days=4)
    )

    assert result.signal == "Orange"
    assert result.matched_rule == "BCD >= 61 AND TCWRS >= 41 AND ETI5_total >= 2"


def test_incomplete_bcd_status_blocks_bcd_decision_rules():
    result = resolve_five_light_signal(
        DecisionMatrixInput(
            tcwrs=20,
            eti5_total=0,
            tail_risk=0,
            bcd=80,
            bcd_status="INCOMPLETE",
            taiex=80,
            ma20=90,
            consecutive_down_days=4,
        )
    )

    assert result.signal == "Green"
    assert result.matched_rule == "Default/green light conditions"
    assert result.trace_output["bcd"] is None
    assert result.trace_output["bcd_status"] == "INCOMPLETE"


def test_bear_trend_filter_applies_floor_without_changing_tcwrs():
    bear = score_bear_trend_filter(
        BearTrendInput(close=80, ma20=90, ma60=100, previous_ma60=101, return_60d_pct=-12)
    )
    result = resolve_five_light_signal(
        DecisionMatrixInput(tcwrs=0, eti5_total=0, tail_risk=0, bcd=0, taiex=80, ma20=90, consecutive_down_days=0),
        bear_trend=bear,
    )

    assert bear.score == 4
    assert bear.floor_signal == "Orange"
    assert result.signal == "Orange"
    assert result.trace_output["tcwrs"] == 0


def test_cal_stays_dormant_for_slow_bear_deterioration_without_acute_velocity():
    from tdt_rm import CrashAccelerationInput, score_crash_acceleration_layer

    cal = score_crash_acceleration_layer(
        CrashAccelerationInput(
            short_window_return_pct=-1.5,
            drawdown_velocity_pct=-2.0,
            volatility_expansion=2.25,
            liquidity_stress=85,
            limit_down_pressure=False,
        )
    )

    assert cal.cal_score == 0
    assert cal.floor_signal is None
    assert cal.conditions["volatility_expansion"] is True
    assert cal.conditions["liquidity_stress"] is True


def test_cal_acute_crash_override_responds_to_velocity_stress_and_limit_pressure():
    from tdt_rm import CrashAccelerationInput, score_crash_acceleration_layer

    cal = score_crash_acceleration_layer(
        CrashAccelerationInput(
            short_window_return_pct=-5.5,
            drawdown_velocity_pct=-6.25,
            volatility_expansion=2.0,
            liquidity_stress=75,
            limit_down_pressure=True,
        )
    )

    assert cal.cal_score == 5
    assert cal.floor_signal == "Red"


def test_signal_after_cal_only_upgrades_and_never_downgrades_baseline_signal():
    from tdt_rm import CrashAccelerationResult

    red_baseline = resolve_five_light_signal(
        DecisionMatrixInput(tcwrs=76, eti5_total=0, tail_risk=0, bcd=0, taiex=100, ma20=100, consecutive_down_days=0),
        cal=CrashAccelerationResult(score=2, floor_signal="Orange", conditions={"synthetic": True}),
    )
    upgraded = resolve_five_light_signal(
        DecisionMatrixInput(tcwrs=0, eti5_total=0, tail_risk=0, bcd=0, taiex=100, ma20=100, consecutive_down_days=0),
        cal=CrashAccelerationResult(score=2, floor_signal="Orange", conditions={"synthetic": True}),
    )

    assert red_baseline.signal == "Red"
    assert red_baseline.trace_output["signal_before_cal"] == "Red"
    assert red_baseline.trace_output["signal_after_cal"] == "Red"
    assert upgraded.signal == "Orange"
    assert upgraded.trace_output["signal_before_cal"] == "Green"
    assert upgraded.trace_output["signal_after_cal"] == "Orange"
