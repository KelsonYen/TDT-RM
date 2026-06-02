from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate_v5_1_4_cal_final_assessment_report.py"
_SPEC = importlib.util.spec_from_file_location("final_assessment", _SCRIPT)
final_assessment = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = final_assessment
assert _SPEC.loader is not None
_SPEC.loader.exec_module(final_assessment)


def _write_csv(path: Path, signal: str = "Orange") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["Date", "Signal", "CP", "Drawdown Avoided %", "False Positive"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "Date": "2024-04-19",
                "Signal": signal,
                "CP": "56.5",
                "Drawdown Avoided %": "8.25",
                "False Positive": "False",
            }
        )


def test_requested_pattern_discovery_finds_cal_tokens_before_year_and_scenario(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    cal_2024 = outputs / "tdt_rm_v5_1_4_cal_2024_ai_selloff_stress.csv"
    cal_2026 = outputs / "tdt_rm_v5_1_4_cal_2026_overheating_stress.csv"
    cal_json = outputs / "tdt_rm_v5_1_4_cal_2024_ai_selloff_summary.json"
    _write_csv(cal_2024)
    _write_csv(cal_2026, signal="Red")
    cal_json.write_text('{"ok": true}\n', encoding="utf-8")

    matches = final_assessment.discover_requested_pattern_matches(outputs)

    assert cal_2024 in matches["cal.csv"]
    assert cal_2026 in matches["cal.csv"]
    assert cal_json in matches["cal.json"]
    assert cal_2024 in matches["2024.csv"]
    assert cal_2026 in matches["2026.csv"]


def test_report_includes_cal_2024_and_2026_rows_when_artifacts_exist(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    _write_csv(outputs / "tdt_rm_v5_1_3_2020_covid_crash_stress.csv", signal="Green")
    _write_csv(outputs / "tdt_rm_v5_1_4_2022_bear_market_backtest.csv", signal="Orange")
    _write_csv(outputs / "tdt_rm_v5_1_4_cal_2024_ai_selloff_stress.csv", signal="Orange")
    _write_csv(outputs / "tdt_rm_v5_1_4_cal_2026_overheating_stress.csv", signal="Red")

    report = final_assessment.build_report(outputs_dir=outputs)

    assert "V5.1.4+CAL" in report
    assert "2024 AI/semiconductor selloff | V5.1.4+CAL" in report
    assert "2026 overheating regime | V5.1.4+CAL" in report
    assert "tdt_rm_v5_1_4_cal_2024_ai_selloff_stress.csv" in report
    assert "tdt_rm_v5_1_4_cal_2026_overheating_stress.csv" in report
    assert "no V5.1.4+CAL artifacts" not in report.lower()


def test_missing_cal_section_lists_specific_file_names(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    _write_csv(outputs / "tdt_rm_v5_1_4_cal_2024_ai_selloff_stress.csv")

    report = final_assessment.build_report(outputs_dir=outputs)

    assert "tdt_rm_v5_1_4_cal_2020_covid_crash_stress.csv" in report
    assert "tdt_rm_v5_1_4_cal_2026_overheating_stress.csv" in report
    assert "all CAL outputs are absent" not in report
