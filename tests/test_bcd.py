from tdt_rm.bcd import BCDInput, BreadthBar, score_bcd


def base_input(**overrides):
    values = dict(
        taiex_return_pct=1.2,
        advancing_issues=400,
        declining_issues=700,
        breadth_history=(BreadthBar(advancing_issues=700, declining_issues=300), BreadthBar(advancing_issues=650, declining_issues=350)),
        main7_returns={"2330": 1.0, "2454": 0.5},
        main7_weights={"2330": 0.7, "2454": 0.3},
        sector_returns={"semis": -0.2, "finance": -0.1, "shipping": 0.3},
        sector_above_ma20={"semis": False, "finance": False, "shipping": True},
        otc_return_pct=-0.4,
        small_mid_breadth=BreadthBar(advancing_issues=250, declining_issues=750),
        turnover_concentration_topn=0.42,
    )
    values.update(overrides)
    return BCDInput(**values)


def test_taiex_up_with_more_decliners_raises_bcd():
    result = score_bcd(base_input())
    assert result.component_scores["index_breadth_divergence"] > 0
    assert result.final_score > 0
    assert result.threshold_hits["index_breadth_divergence.decliners_gt_advancers"] is True


def test_main7_strong_breadth_weak_scores_concentration():
    result = score_bcd(
        base_input(
            main7_returns={"2330": 3.0, "2454": 2.5},
            main7_weights={"2330": 0.65, "2454": 0.35},
        )
    )
    assert result.component_scores["main7_concentration"] > 0


def test_final_score_is_component_sum():
    result = score_bcd(
        base_input(
            main7_returns={"2330": 3.0},
            main7_weights={"2330": 1.0},
            turnover_concentration_topn=0.55,
        )
    )
    assert result.final_score == round(sum(result.component_scores.values()), 4)


def test_missing_required_inputs_never_create_synthetic_score():
    result = score_bcd(base_input(main7_returns={}, main7_weights={}, otc_return_pct=None))

    assert result.final_score is None
    assert result.data_quality_status == "INCOMPLETE"
    assert "main7_returns" in result.missing_components
    assert "main7_weights" in result.missing_components
    assert "otc_return_pct" in result.missing_components


def test_bcd_changes_while_tail_risk_can_remain_fixed():
    fixed_tail_risk = 42.0

    low_bcd = score_bcd(base_input(advancing_issues=800, declining_issues=300, turnover_concentration_topn=0.10))
    high_bcd = score_bcd(base_input(advancing_issues=300, declining_issues=900, turnover_concentration_topn=0.60))

    assert fixed_tail_risk == 42.0
    assert low_bcd.final_score != high_bcd.final_score


def test_tail_risk_changes_while_bcd_can_remain_fixed():
    result = score_bcd(base_input())

    assert result.final_score == score_bcd(base_input()).final_score
    assert 10.0 != 90.0


def test_bcd_tail_risk_similarity_fails_after_three_consecutive_days():
    from tdt_rm.bcd import assert_bcd_tail_risk_independence

    rows = [
        {"trade_date": "2026-06-01", "bcd": 20.0, "tail_risk": 20.0},
        {"trade_date": "2026-06-02", "bcd": 21.0, "tail_risk": 21.0},
        {"trade_date": "2026-06-03", "bcd": 22.0, "tail_risk": 22.0},
        {"trade_date": "2026-06-04", "bcd": 23.0, "tail_risk": 23.0},
    ]

    import pytest

    with pytest.raises(ValueError, match="BCD independence violation"):
        assert_bcd_tail_risk_independence(rows)
