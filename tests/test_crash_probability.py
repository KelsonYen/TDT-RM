import pytest

from tdt_rm import (
    CrashProbabilityInput,
    cp_level_for_score,
    score_crash_probability,
)


def test_crash_probability_returns_requested_score_level_and_trace_output():
    result = score_crash_probability(
        CrashProbabilityInput(tcwrs=50, eti5_total=2, tail_risk=60, bcd=70)
    )
    serialized = result.as_dict()

    assert result.cp_raw == 51
    assert result.cp_score == 51
    assert result.cp_level == "Medium"
    assert serialized["cp_score"] == 51
    assert serialized["cp_level"] == "Medium"
    assert serialized["cp_raw"] == 51
    assert serialized["trace_output"]["formula"] == (
        "TCWRS * 0.40 + (ETI5_total * 20) * 0.30 + TailRisk * 0.20 + BCD * 0.10"
    )
    assert serialized["trace_output"]["raw"] == {
        "tcwrs": 50,
        "eti5_total": 2,
        "tail_risk": 60,
        "bcd": 70,
        "bcd_status": "COMPLETE",
    }
    assert serialized["trace_output"]["scaled_inputs"]["eti5_scaled"] == 40
    assert serialized["trace_output"]["contributions"] == {
        "tcwrs": 20,
        "eti5": 12,
        "tail_risk": 12,
        "bcd": 7,
    }
    assert serialized["trace_output"]["cap_applied"] is False


@pytest.mark.parametrize(
    ("cp_score", "expected_level"),
    [
        (0, "Low"),
        (30, "Low"),
        (30.1, "Medium"),
        (55, "Medium"),
        (55.1, "High"),
        (75, "High"),
        (75.1, "Extreme"),
        (100, "Extreme"),
    ],
)
def test_crash_probability_level_boundaries(cp_score, expected_level):
    assert cp_level_for_score(cp_score) == expected_level


def test_crash_probability_caps_scores_above_100():
    result = score_crash_probability(
        CrashProbabilityInput(tcwrs=120, eti5_total=5, tail_risk=150, bcd=150)
    )

    assert result.cp_raw == 123
    assert result.cp_score == 100
    assert result.cp_level == "Extreme"
    assert result.trace_output["cap_applied"] is True


@pytest.mark.parametrize("eti5_total", [-0.1, 5.1])
def test_crash_probability_rejects_eti5_total_outside_valid_range(eti5_total):
    with pytest.raises(ValueError, match="ETI5_total"):
        score_crash_probability(
            CrashProbabilityInput(
                tcwrs=0,
                eti5_total=eti5_total,
                tail_risk=0,
                bcd=0,
            )
        )


def test_crash_probability_excludes_bcd_when_status_is_incomplete():
    result = score_crash_probability(
        CrashProbabilityInput(tcwrs=50, eti5_total=2, tail_risk=60, bcd=70, bcd_status="INCOMPLETE")
    )

    assert result.cp_raw == 44
    assert result.trace_output["raw"]["bcd"] is None
    assert result.trace_output["input_status"]["bcd"] == "missing_excluded_from_cp_contribution"
    assert result.trace_output["input_status"]["bcd_status"] == "INCOMPLETE"
