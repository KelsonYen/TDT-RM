from tdt_rm import DecisionMatrixInput, resolve_five_light_signal


def test_red_precedes_orange():
    result = resolve_five_light_signal(
        DecisionMatrixInput(tcwrs=76, eti5_total=2, tail_risk=80, bcd=80, taiex=100, ma20=90, consecutive_down_days=1)
    )
    assert result.signal == "Red"
    assert result.matched_rule == "TCWRS >= 76"


def test_bcd_orange_requires_confirmation_context():
    invalid = resolve_five_light_signal(
        DecisionMatrixInput(tcwrs=45, eti5_total=2, tail_risk=20, bcd=80, taiex=80, ma20=90, consecutive_down_days=1)
    )
    valid = resolve_five_light_signal(
        DecisionMatrixInput(tcwrs=45, eti5_total=2, tail_risk=20, bcd=80, taiex=100, ma20=90, consecutive_down_days=1)
    )
    assert invalid.signal == "Strengthened Yellow"
    assert valid.signal == "Orange"
