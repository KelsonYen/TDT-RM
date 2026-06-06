import csv
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from tdt_rm.bcd import BCDInput, BreadthBar, score_bcd
from tdt_rm.daily_pipeline import run_daily_pipeline, write_final_operator_reports, write_json_summary

import importlib.util
import sys

_VALIDATE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_daily_input_csvs.py"
_SPEC = importlib.util.spec_from_file_location("validate_daily_input_csvs", _VALIDATE_PATH)
assert _SPEC and _SPEC.loader
_VALIDATE_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _VALIDATE_MODULE
_SPEC.loader.exec_module(_VALIDATE_MODULE)
validate_daily_input_csvs = _VALIDATE_MODULE.validate_daily_input_csvs

INPUT_DIR = Path("inputs/daily/2026-06-05")
FORBIDDEN_MESSAGE = "Provider-supplied BCD is forbidden. BCD must be computed only by score_bcd(BCDInput(…))."


def _copy_inputs(dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("price.csv", "foreign_flow.csv", "fx.csv", "breadth.csv", "futures.csv", "options.csv", "leadership.csv", "margin.csv"):
        shutil.copy2(INPUT_DIR / name, dst / name)


def _append_bcd_column(path: Path, value: str = "53.95") -> None:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0].keys()) if rows else list(csv.DictReader(handle).fieldnames or [])
    fieldnames.append("bcd")
    for row in rows:
        row["bcd"] = value
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_provider_csv_with_bcd_column_validation_fails(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    _copy_inputs(inputs)
    _append_bcd_column(inputs / "breadth.csv")

    errors = validate_daily_input_csvs(trade_date=date(2026, 6, 5), input_dir=inputs)

    assert any("breadth.csv: forbidden provider BCD column(s): bcd" in error for error in errors)
    assert any(FORBIDDEN_MESSAGE in error for error in errors)


def test_options_csv_with_bcd_column_pipeline_fails(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    _copy_inputs(inputs)
    _append_bcd_column(inputs / "options.csv")

    with pytest.raises(ValueError, match="Provider-supplied BCD is forbidden"):
        run_daily_pipeline(
            as_of=date(2026, 6, 5),
            output_dir=tmp_path / "out",
            price_csv=inputs / "price.csv",
            foreign_csv=inputs / "foreign_flow.csv",
            fx_csv=inputs / "fx.csv",
            breadth_csv=inputs / "breadth.csv",
            futures_csv=inputs / "futures.csv",
            options_csv=inputs / "options.csv",
            leadership_csv=inputs / "leadership.csv",
            margin_csv=inputs / "margin.csv",
        )


def test_assembled_snapshot_excludes_provider_derived_bcd_and_incomplete_daily_json(tmp_path: Path) -> None:
    result = run_daily_pipeline(
        as_of=date(2026, 6, 5),
        output_dir=tmp_path / "out",
        price_csv=INPUT_DIR / "price.csv",
        foreign_csv=INPUT_DIR / "foreign_flow.csv",
        fx_csv=INPUT_DIR / "fx.csv",
        breadth_csv=INPUT_DIR / "breadth.csv",
        futures_csv=INPUT_DIR / "futures.csv",
        options_csv=INPUT_DIR / "options.csv",
        leadership_csv=INPUT_DIR / "leadership.csv",
        margin_csv=INPUT_DIR / "margin.csv",
    )

    snapshot = json.loads(Path(result["artifact_paths"]["assembled_snapshot"]).read_text(encoding="utf-8"))
    payload = json.loads(Path(result["artifact_paths"]["json"]).read_text(encoding="utf-8"))

    assert "bcd" not in snapshot["canonical_row"]
    assert "bcd" not in snapshot["field_sources"]
    assert payload["bcd"] is None
    assert payload["bcd_status"] == "INCOMPLETE"
    assert payload["scores"]["BCD"] is None


def test_report_does_not_render_stale_or_provider_bcd(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    reports_dir = tmp_path / "reports"
    summary_path = output_dir / "pipeline_summary.json"
    result = run_daily_pipeline(
        as_of=date(2026, 6, 5),
        output_dir=output_dir,
        price_csv=INPUT_DIR / "price.csv",
        foreign_csv=INPUT_DIR / "foreign_flow.csv",
        fx_csv=INPUT_DIR / "fx.csv",
        breadth_csv=INPUT_DIR / "breadth.csv",
        futures_csv=INPUT_DIR / "futures.csv",
        options_csv=INPUT_DIR / "options.csv",
        leadership_csv=INPUT_DIR / "leadership.csv",
        margin_csv=INPUT_DIR / "margin.csv",
    )
    write_json_summary(result, summary_path)
    paths = write_final_operator_reports(result, reports_dir, pipeline_summary_path=summary_path)

    report = paths["dated"].read_text(encoding="utf-8")

    assert "BCD：資料不足" in report
    assert "BCD | 53.95" not in report
    assert "BCD：53.95" not in report


def test_bcd_complete_calculation_comes_from_score_bcd_input_only() -> None:
    bcd_input = BCDInput(
        taiex_return_pct=1.2,
        advancing_issues=300,
        declining_issues=900,
        breadth_history=(BreadthBar(advancing_issues=350, declining_issues=850), BreadthBar(advancing_issues=300, declining_issues=900)),
        main7_returns={"2330": 3.0, "0050": 2.0},
        main7_weights={"2330": 0.6, "0050": 0.4},
        sector_returns={"semis": 1.0, "finance": -1.0, "shipping": -0.5},
        sector_above_ma20={"semis": True, "finance": False, "shipping": False},
        otc_return_pct=-1.0,
        small_mid_breadth=BreadthBar(advancing_issues=150, declining_issues=450),
        turnover_concentration_topn=0.55,
    )

    result = score_bcd(bcd_input)

    assert result.data_quality_status == "COMPLETE"
    assert result.final_score is not None
    assert result.calculation_version == "BCD-INDEPENDENT-V1"
