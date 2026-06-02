import csv
import json
from pathlib import Path

from tdt_rm import validate_2022_bear_market_backtest


def _write_artifacts(tmp_path: Path, rows: list[dict[str, object]], summary: dict[str, object] | None = None):
    csv_path = tmp_path / "backtest.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    summary_path = tmp_path / "summary.json"
    if summary is None:
        summary = {
            "observations": len(rows),
            "red_signals": sum(row["Signal"] == "Red" for row in rows),
            "orange_signals": sum(row["Signal"] == "Orange" for row in rows),
            "false_positives": sum(row["False Positive"] is True for row in rows),
            "maximum_drawdown_avoided_pct": max(float(row["Drawdown Avoided %"]) for row in rows),
        }
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    return csv_path, summary_path


def _valid_row(date: str) -> dict[str, object]:
    return {
        "Date": date,
        "TCWRS": 20,
        "ETI-5": 1,
        "eti_available_count": 1,
        "eti_raw_score": 1,
        "eti_capped_score": 1,
        "eti_cap_reason": "available components <= 2; capped at 2",
        "red_confirmed_by": "",
        "Signal": "Yellow",
        "Close": 100,
        "forward_20d_max_drawdown": -1.0,
        "forward_40d_max_drawdown": -2.0,
        "forward_60d_max_drawdown": -3.0,
        "false_positive_20d": False,
        "false_positive_40d": False,
        "false_positive_60d": False,
        "delayed_valid_signal": False,
        "False Positive": False,
        "Drawdown Avoided %": 0.0,
    }


def test_validate_2022_bear_market_backtest_accepts_expected_artifacts(tmp_path: Path):
    rows = [_valid_row("2022-01-03")]
    rows.extend(_valid_row(f"2022-01-{day:02d}") for day in range(4, 31))
    rows.extend(_valid_row(f"2022-12-{day:02d}") for day in range(1, 31))
    while len(rows) < 247:
        rows.insert(-30, _valid_row(f"2022-06-{(len(rows) % 28) + 1:02d}"))
    rows[-1]["Date"] = "2022-12-30"
    csv_path, summary_path = _write_artifacts(tmp_path, rows)

    result = validate_2022_bear_market_backtest(csv_path, summary_path)

    assert result.is_valid is True
    assert {check.name for check in result.checks} == {
        "observation_window",
        "required_columns",
        "price_only_eti_controls",
        "red_signal_confirmation",
        "outcome_annotations",
        "summary_matches_rows",
    }


def test_validate_2022_bear_market_backtest_flags_eti_overpromotion(tmp_path: Path):
    rows = [_valid_row("2022-01-03") for _ in range(247)]
    rows[-1]["Date"] = "2022-12-30"
    rows[10]["Signal"] = "Red"
    rows[10]["TCWRS"] = 40
    rows[10]["eti_available_count"] = 1
    csv_path, summary_path = _write_artifacts(tmp_path, rows)

    result = validate_2022_bear_market_backtest(csv_path, summary_path)

    assert result.is_valid is False
    failed = {check.name for check in result.checks if not check.passed}
    assert "red_signal_confirmation" in failed
