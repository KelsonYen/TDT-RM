from __future__ import annotations

import csv
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from tdt_rm.bcd import BCDInput, score_bcd
from tdt_rm.daily_runner import _bcd_result_from_snapshot
from tdt_rm.daily_snapshot import DailyMarketSnapshot
from tdt_rm.data_providers.normalizers import STRICT_COLUMNS, normalize_public_row

MAIN7_LINEAGE_FIELDS = ("main7_closes", "main7_previous_closes", "main7_turnover_amounts")


def test_production_leadership_csvs_declare_main7_lineage_fields():
    for path in (
        Path("inputs/daily/2026-06-05/leadership.csv"),
        Path("inputs/daily/2026-06-05/_strict_provider_csvs/leadership.csv"),
    ):
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            assert set(MAIN7_LINEAGE_FIELDS) <= set(reader.fieldnames or ())


def test_strict_leadership_normalizer_preserves_main7_lineage_values():
    row = normalize_public_row(
        "leadership",
        {
            "count_main_7_below_ma20": 0,
            "count_main_7_below_ma60": 0,
            "majority_main_7_assets_above_ma20": True,
            "main_7_symbols": "2330,2454",
            "main7_closes": {"2330": 110, "2454": 190},
            "main7_previous_closes": {"2330": 100, "2454": 200},
            "main7_turnover_amounts": {"2330": 30, "2454": 70},
        },
        trade_date=date(2026, 6, 5),
        provider_source="TWSE_OFFICIAL:twse_main7_leadership",
    )

    assert set(MAIN7_LINEAGE_FIELDS) <= set(STRICT_COLUMNS["leadership"])
    assert row["main7_closes"] == {"2330": 110, "2454": 190}
    assert row["main7_previous_closes"] == {"2330": 100, "2454": 200}
    assert row["main7_turnover_amounts"] == {"2330": 30, "2454": 70}


def test_bcdinput_receives_main7_lineage_fields_when_available():
    snapshot = DailyMarketSnapshot(
        trade_date=date(2026, 6, 5),
        observed_at=date(2026, 6, 5),
        canonical_row={
            "observed_at": "2026-06-05",
            "one_day_return_pct": 1.0,
            "advancing_issues": 60,
            "declining_issues": 40,
            "main7_closes": {"2330": 110},
            "main7_previous_closes": {"2330": 100},
            "main7_turnover_amounts": {"2330": 10},
            "main7_returns": {"2330": 10.0},
            "main7_weights": {"2330": 1.0},
        },
        field_sources={
            "one_day_return_pct": "price_csv",
            "advancing_issues": "breadth_csv",
            "declining_issues": "breadth_csv",
            "main7_closes": "leadership_csv",
            "main7_previous_closes": "leadership_csv",
            "main7_turnover_amounts": "leadership_csv",
            "main7_returns": "bcd_feature_builder",
            "main7_weights": "bcd_feature_builder",
        },
    )

    result = _bcd_result_from_snapshot(snapshot, taiex_return_pct=1.0)

    assert result.raw_inputs["main7_closes"] == {"2330": 110.0}
    assert result.raw_inputs["main7_previous_closes"] == {"2330": 100.0}
    assert result.raw_inputs["main7_turnover_amounts"] == {"2330": 10.0}
    assert result.source_fields["main7_closes"] == "leadership_csv"


def test_bcd_is_incomplete_and_null_when_main7_required_fields_are_missing():
    result = score_bcd(
        BCDInput(
            taiex_return_pct=1.0,
            advancing_issues=60,
            declining_issues=40,
            breadth_history=(),
            main7_returns={},
            main7_weights={},
            sector_returns={},
            sector_above_ma20={},
            otc_return_pct=None,
            small_mid_breadth=None,
            turnover_concentration_topn=None,
        )
    )

    assert result.final_score is None
    assert result.data_quality_status == "INCOMPLETE"
    assert "main7_returns" in result.missing_components
    assert "main7_weights" in result.missing_components


def test_generated_report_marks_incomplete_bcd_and_cp_excludes_it(tmp_path: Path):
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_daily_production_pipeline.py",
            "--trade-date",
            "2026-06-05",
            "--input-dir",
            "inputs/daily/2026-06-05",
            "--outputs-dir",
            str(tmp_path / "artifacts"),
            "--reports-dir",
            str(tmp_path / "reports"),
            "--pipeline-summary",
            str(tmp_path / "artifacts" / "pipeline_summary.json"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads((tmp_path / "artifacts" / "tdt_rm_daily_2026-06-05.json").read_text(encoding="utf-8"))
    report = (tmp_path / "artifacts" / "tdt_rm_daily_2026-06-05.md").read_text(encoding="utf-8")
    cp_trace = payload["traces"]["crash_probability"]["trace_output"]

    assert payload["bcd"] is None
    assert payload["bcd_status"] == "INCOMPLETE"
    assert "BCD：資料不足／INCOMPLETE" in report
    assert "BCD 資料不足，未納入升燈判斷" in report
    assert cp_trace["raw"]["bcd"] is None
    assert cp_trace["contributions"]["bcd"] == 0.0
    assert cp_trace["input_status"]["bcd"] == "missing_excluded_from_cp_contribution"


def test_trace_command_reports_main7_and_bcd_stages_without_old_complete_fallback():
    for field in (*MAIN7_LINEAGE_FIELDS, "bcd"):
        completed = subprocess.run(
            [sys.executable, "scripts/trace_daily_lineage.py", "--trade-date", "2026-06-05", "--field", field],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert ("Provider raw row:" in completed.stdout) or ("Provider fetch summary:" in completed.stdout)
        assert "Legacy rerun outputs:" in completed.stdout
    bcd = subprocess.run(
        [sys.executable, "scripts/trace_daily_lineage.py", "--trade-date", "2026-06-05", "--field", "bcd"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "Daily JSON status: FOUND" in bcd
    assert "INCOMPLETE" in bcd
