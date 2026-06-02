from tdt_rm import ETI5Input, score_eti5


def base_input(**overrides):
    data = {
        "close": 100.0,
        "ma20": 95.0,
    }
    data.update(overrides)
    return ETI5Input(**data)


def test_eti5_returns_requested_zero_score_triggered_signals_and_trace_output():
    result = score_eti5(base_input())
    serialized = result.as_dict()

    assert result.eti_score == 0
    assert result.eti5_total == 0
    assert result.triggered_signals == []
    assert serialized["eti_score"] == 0
    assert serialized["triggered_signals"] == []
    assert set(serialized["trace_output"]) == {
        "ETI-1",
        "ETI-2",
        "ETI-3",
        "ETI-4",
        "ETI-5",
    }
    assert serialized["trace_output"]["ETI-5"]["name"] == "Leadership breakdown"
    assert serialized["trace_output"]["ETI-5"]["triggered"] is False


def test_eti5_scores_all_five_components_and_preserves_audit_trace():
    result = score_eti5(
        base_input(
            close=94,
            ma20=95,
            foreign_spot_net_sell_consecutive_days=2,
            usd_twd_3d_change_pct=0.51,
            index_down=True,
            declining_issues_significantly_gt_advancing=True,
            count_main_7_below_ma20=4,
        )
    )

    assert result.eti_score == 5
    assert result.triggered_signals == ["ETI-1", "ETI-2", "ETI-3", "ETI-4", "ETI-5"]
    assert result.trace_output["ETI-1"]["trace_output"]["close_lt_ma20"] is True
    assert result.trace_output["ETI-2"]["matched_rule"] == (
        "foreign_spot_net_sell_for_2_days OR (foreign_large_sell AND futures_hedging_increases)"
    )
    assert (
        result.trace_output["ETI-3"]["trace_output"]["usd_twd_3d_change_gt_0_5"] is True
    )
    assert (
        result.trace_output["ETI-4"]["trace_output"][
            "index_down_and_declining_issues_significantly_gt_advancing"
        ]
        is True
    )
    assert (
        result.trace_output["ETI-5"]["trace_output"]["count_main_7_below_ma20_gte_4"]
        is True
    )


def test_eti5_component_alternate_paths_trigger_expected_signals():
    result = score_eti5(
        base_input(
            close=96,
            ma20=95,
            close_not_back_above_ma20_for_2_days=True,
            foreign_large_sell=True,
            futures_hedging_increases=True,
            usd_twd_5d_change_pct=1.01,
            breadth_weakens_for_2_days=True,
            count_main_7_below_ma20=5,
        )
    )

    assert result.eti_score == 5
    assert result.triggered_signals == ["ETI-1", "ETI-2", "ETI-3", "ETI-4", "ETI-5"]
    assert (
        result.trace_output["ETI-1"]["trace_output"][
            "close_not_back_above_ma20_for_2_days"
        ]
        is True
    )
    assert (
        result.trace_output["ETI-2"]["trace_output"][
            "foreign_large_sell_and_futures_hedging_increases"
        ]
        is True
    )
    assert (
        result.trace_output["ETI-3"]["trace_output"]["usd_twd_5d_change_gt_1_0"] is True
    )
    assert (
        result.trace_output["ETI-4"]["trace_output"]["breadth_weakens_for_2_days"]
        is True
    )
    assert (
        result.trace_output["ETI-5"]["trace_output"][
            "count_main_7_below_ma20_gte_5_high_risk_confirmation"
        ]
        is True
    )


def test_eti5_threshold_edges_are_strict_where_spec_requires():
    result = score_eti5(
        base_input(
            close=95,
            ma20=95,
            foreign_spot_net_sell_consecutive_days=1,
            usd_twd_3d_change_pct=0.5,
            usd_twd_5d_change_pct=1.0,
            index_down=True,
            declining_issues_significantly_gt_advancing=False,
            count_main_7_below_ma20=3,
        )
    )

    assert result.eti_score == 0
    assert result.triggered_signals == []
    assert result.trace_output["ETI-1"]["trace_output"]["close_lt_ma20"] is False
    assert (
        result.trace_output["ETI-3"]["trace_output"]["usd_twd_3d_change_gt_0_5"]
        is False
    )
    assert (
        result.trace_output["ETI-3"]["trace_output"]["usd_twd_5d_change_gt_1_0"]
        is False
    )
    assert (
        result.trace_output["ETI-5"]["trace_output"]["count_main_7_below_ma20_gte_4"]
        is False
    )


def test_eti5_v514_availability_caps_price_only_backtests():
    result = score_eti5(
        base_input(
            close=94,
            ma20=95,
            foreign_spot_net_sell_consecutive_days=2,
            usd_twd_3d_change_pct=0.6,
            index_down=True,
            declining_issues_significantly_gt_advancing=True,
            count_main_7_below_ma20=4,
            available_components={"ETI-1"},
        )
    )

    assert result.eti_available_count == 1
    assert result.eti_raw_score == 1
    assert result.eti_capped_score == 1
    assert result.eti_score == 1
    assert result.eti_cap_reason == "available components <= 2; capped at 2"
    assert result.triggered_signals == ["ETI-1"]
    assert result.trace_output["ETI-2"]["available"] is False
    assert result.trace_output["ETI-2"]["triggered"] is False


def test_eti5_v514_caps_three_available_components_at_three():
    result = score_eti5(
        base_input(
            close=94,
            ma20=95,
            foreign_spot_net_sell_consecutive_days=2,
            usd_twd_3d_change_pct=0.6,
            count_main_7_below_ma20=4,
            available_components={"ETI-1", "ETI-2", "ETI-3"},
        )
    )

    assert result.eti_available_count == 3
    assert result.eti_raw_score == 3
    assert result.eti_capped_score == 3
    assert result.eti_cap_reason == "available components = 3; capped at 3"
