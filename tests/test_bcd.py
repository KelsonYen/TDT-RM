from tdt_rm.bcd import BCDInput, BreadthBar, score_bcd


def base_input(**overrides):
    values = dict(
        taiex_return_pct=1.2,
        advancing_issues=400,
        declining_issues=700,
        breadth_history=(BreadthBar(advancing_issues=700, declining_issues=300), BreadthBar(advancing_issues=650, declining_issues=350)),
        main7_returns={},
        main7_weights={},
        sector_returns={},
        sector_above_ma20={},
        otc_return_pct=None,
        small_mid_breadth=None,
        turnover_concentration_topn=None,
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
