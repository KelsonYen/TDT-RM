from tdt_rm.bcd import BCDInput, BreadthBar, score_bcd


def test_sector_breadth_missing_is_disclosed():
    result = score_bcd(
        BCDInput(
            taiex_return_pct=0.8,
            advancing_issues=500,
            declining_issues=800,
            breadth_history=(BreadthBar(700, 300),),
            main7_returns={},
            main7_weights={},
            sector_returns={},
            sector_above_ma20={},
            otc_return_pct=None,
            small_mid_breadth=None,
            turnover_concentration_topn=None,
        )
    )
    assert "sector_breadth" in result.missing_components
    assert result.data_quality_status == "partial"


def test_turnover_concentration_scores_only_when_broad_participation_weak():
    result = score_bcd(
        BCDInput(
            taiex_return_pct=1.0,
            advancing_issues=300,
            declining_issues=900,
            breadth_history=(BreadthBar(700, 300),),
            main7_returns={},
            main7_weights={},
            sector_returns={},
            sector_above_ma20={},
            otc_return_pct=None,
            small_mid_breadth=None,
            turnover_concentration_topn=0.52,
        )
    )
    assert result.component_scores["turnover_concentration"] > 0
    assert result.threshold_hits["turnover_concentration.topn_share_ge_50pct"] is True


def test_trace_contains_required_keys():
    result = score_bcd(
        BCDInput(
            taiex_return_pct=1.0,
            advancing_issues=300,
            declining_issues=900,
            breadth_history=(BreadthBar(700, 300),),
            main7_returns={},
            main7_weights={},
            sector_returns={"tech": -1.0, "finance": -0.5, "shipping": 0.2},
            sector_above_ma20={"tech": False, "finance": False, "shipping": True},
            otc_return_pct=None,
            small_mid_breadth=None,
            turnover_concentration_topn=0.52,
        )
    ).as_dict()
    for key in ("final_score", "component_scores", "raw_inputs", "threshold_hits", "missing_components", "source_fields", "data_quality_status"):
        assert key in result
