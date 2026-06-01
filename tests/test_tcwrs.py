from tdt_rm import TCWRSInput, score_tcwrs
from tdt_rm.tcwrs import score_b, score_f, score_g, score_l, score_m, score_p, score_v, score_x


def base_input(**overrides):
    data = {
        "close": 100.0,
        "ma5": 99.0,
        "ma20": 95.0,
        "ma60": 90.0,
        "ma20_slope": 1.0,
    }
    data.update(overrides)
    return TCWRSInput(**data)


def test_price_trend_and_downside_speed_scores_and_traces_intermediates():
    assert score_p(base_input()).score == 0
    assert score_p(base_input(close=96, ma5=101, ma20=95, ma20_slope=0)).score == 4
    assert score_p(base_input(close=94, ma20=95, close_below_ma20_consecutive_days=1)).score == 8
    assert score_p(base_input(close=94, ma20=95, close_below_ma20_consecutive_days=2)).score == 12
    assert score_p(base_input(close=89, ma20=95, ma60=90)).score == 15

    result = score_p(base_input(close=100, ma20=95, ma20_slope=-1, one_day_return_pct=-3.5))

    assert result.score == 18
    assert result.conditions["one_day_return_lte_minus_3_5_or_two_day_return_lte_minus_5_5"] is True
    assert result.conditions["raw"]["one_day_return_pct"] == -3.5


def test_volume_price_efficiency_uses_spec_high_volume_definition():
    assert score_v(base_input(volume_up=True, price_up=True, close_is_red=True)).score == 0
    assert score_v(base_input(turnover_amount=151, ma20_turnover=100, high_level=True, close_is_red=True)).score == 3
    assert score_v(base_input(high_level=True, long_upper_shadow=True)).score == 6
    assert score_v(base_input(turnover_amount=151, ma20_turnover=100, close_is_black=True)).score == 9

    result = score_v(
        base_input(
            close=94,
            ma20=95,
            turnover_top_10pct_1y=True,
            long_black_candle=True,
        )
    )

    assert result.score == 12
    assert result.conditions["high_volume"] is True
    assert result.conditions["raw"]["turnover_top_10pct_1y"] is True


def test_foreign_investor_spot_futures_options_scores():
    assert score_f(base_input(foreign_spot_net_buy=1, futures_net_short_decreases=True, pcr_stable=True, vix_stable=True)).score == 0
    assert score_f(base_input(foreign_spot_small_sell=True, futures_hedging_significant=False)).score == 4
    assert score_f(base_input(foreign_spot_net_sell_consecutive_days=2)).score == 8

    result = score_f(base_input(foreign_spot_large_sell=True, futures_net_short_increases=True, vix_rises=True))

    assert result.score == 15
    assert result.conditions["foreign_spot_large_sell_and_futures_net_short_increases_and_pcr_or_vix_rises"] is True


def test_fx_cross_border_capital_scores():
    assert score_x(base_input(twd_stable=True)).score == 0
    assert score_x(base_input(usd_twd_3d_change_pct=0.51)).score == 4
    assert score_x(base_input(usd_twd_5d_change_pct=1.01)).score == 8

    result = score_x(base_input(index_down=True, twd_depreciates_significantly=True, foreign_spot_net_sell=True))

    assert result.score == 12
    assert result.conditions["index_down_and_twd_depreciates_significantly_and_foreign_spot_net_sell"] is True


def test_margin_leverage_retail_scores():
    assert score_m(base_input(margin_balance_5d_flat_or_down=True, hot_stock_margin_fast_increase=False)).score == 0
    assert score_m(base_input(margin_balance_5d_increases=True, close=96, ma20=95)).score == 4
    assert score_m(base_input(index_5d_return_pct=-3.01, margin_balance_5d_decline_pct=0.49)).score == 8
    assert score_m(base_input(index_down=True, margin_not_retreating=True, hot_stock_margin_fast_increase=True)).score == 12


def test_market_breadth_deterioration_scores_and_keeps_bcd_case_out():
    assert score_b(base_input(index_up_or_flat=True, advancing_issues=600, declining_issues=400)).score == 0
    assert score_b(base_input(index_down=True, declining_issues_significantly_expand=False)).score == 4
    assert score_b(base_input(index_down=True, declining_issues_significantly_expand=True, declining_issues_significantly_gt_advancing=True)).score == 8

    result = score_b(base_input(close=94, ma20=95, declining_gt_advancing_consecutive_days=2))

    assert result.score == 12
    assert result.conditions["close_lt_ma20_and_declining_gt_advancing_for_2_consecutive_days"] is True

    # Spec rule: index-up breadth deterioration is not scored under TCWRS_B.
    assert score_b(base_input(index_up_or_flat=True, advancing_issues=300, declining_issues=700)).score == 0


def test_large_cap_mainstream_health_scores():
    assert score_l(base_input(majority_main_7_assets_above_ma20=True)).score == 0
    assert score_l(base_input(count_main_7_below_ma20=2)).score == 3
    assert score_l(base_input(count_main_7_below_ma20=4)).score == 6
    assert score_l(base_input(count_main_7_below_ma20=5)).score == 8
    assert score_l(base_input(count_main_7_below_ma60=4)).score == 10


def test_global_risk_external_pressure_scores_without_valuation():
    assert score_g(base_input(us_stocks_stable=True, sox_stable=True, vix_stable_global=True)).score == 0
    assert score_g(base_input(sox=99, sox_ma20=100, sox_ma60=90, nasdaq=101, nasdaq_ma20=100)).score == 3
    assert score_g(base_input(sox=89, sox_ma20=80, sox_ma60=90, nasdaq=101, nasdaq_ma20=100)).score == 6

    result = score_g(base_input(close=94, ma20=95, us_tech_leadership_weakens=True, vix_spikes=True))

    assert result.score == 9
    assert "valuation" not in result.conditions


def test_complete_tcwrs_result_preserves_all_factor_scores_and_conditions():
    result = score_tcwrs(
        base_input(
            close=94,
            ma20=95,
            close_below_ma20_consecutive_days=1,
            turnover_top_10pct_1y=True,
            close_is_black=True,
            foreign_spot_net_sell_consecutive_days=2,
            usd_twd_5d_change_pct=1.01,
            index_5d_return_pct=-3.01,
            margin_balance_5d_decline_pct=0.49,
            index_down=True,
            declining_issues_significantly_expand=True,
            declining_issues_significantly_gt_advancing=True,
            count_main_7_below_ma20=4,
            sox=99,
            sox_ma20=100,
            sox_ma60=90,
            nasdaq=101,
            nasdaq_ma20=100,
        )
    )

    assert set(result.factors) == {"P", "V", "F", "X", "M", "B", "L", "G"}
    assert result.total == 58
    trace = result.as_dict()
    assert trace["factors"]["P"]["conditions"]["raw"]["close"] == 94
    assert trace["factors"]["G"]["max_score"] == 9
