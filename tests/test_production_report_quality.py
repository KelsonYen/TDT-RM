import json
from datetime import date
from pathlib import Path

from tdt_rm.daily_pipeline import render_final_operator_report, run_daily_pipeline
from tdt_rm.daily_validation import validate_daily_artifacts


TRADE_DATE = date(2026, 6, 5)
INPUT_DIR = Path("inputs/daily/2026-06-05")


def test_2026_06_05_fallback_options_and_disclosures_fail_operator_quality(tmp_path: Path):
    result = run_daily_pipeline(
        as_of=TRADE_DATE,
        output_dir=tmp_path,
        price_csv=INPUT_DIR / "price.csv",
        foreign_csv=INPUT_DIR / "foreign_flow.csv",
        fx_csv=INPUT_DIR / "fx.csv",
        breadth_csv=INPUT_DIR / "breadth.csv",
        futures_csv=INPUT_DIR / "futures.csv",
        options_csv=INPUT_DIR / "options.csv",
        leadership_csv=INPUT_DIR / "leadership.csv",
        margin_csv=INPUT_DIR / "margin.csv",
        command="pytest",
    )

    daily_json = Path(result["artifact_paths"]["json"])
    daily_markdown = Path(result["artifact_paths"]["markdown"])
    payload = json.loads(daily_json.read_text(encoding="utf-8"))
    validation = validate_daily_artifacts(daily_json, daily_markdown, as_of=TRADE_DATE)
    disclosure = payload["operator_disclosure"]

    assert validation.status == "passed"
    assert result["validation_status"] == "passed"
    assert payload["production_report_quality"] == "FAIL_FOR_OPERATOR_USE"
    assert result["production_report_quality"] == "FAIL_FOR_OPERATOR_USE"
    assert disclosure["acceptable_for_real_world_daily_use"] is False
    assert any(item["provider_source"] == "FINMIND_FALLBACK:TaiwanOptionDaily:TXO" for item in disclosure["fallback_provider_datasets"])
    assert {item["operator_field"] for item in disclosure["fallback_operator_dependencies"]} >= {"Tail Risk", "BCD", "Crash Probability"}
    assert {item["field"] for item in disclosure["placeholder_default_like_fields"]} >= {"nasdaq", "sox"}
    assert any(item["module"] == "ETF Exit" and item["status"] == "not_integrated" for item in disclosure["non_integrated_modules"])

    report = render_final_operator_report(result)
    assert "## Operator Disclosure" in report
    assert "Production Report Quality: `FAIL_FOR_OPERATOR_USE`" in report
    assert "Acceptable for Real-World Daily Use: `NO`" in report
    assert "FINMIND_FALLBACK:TaiwanOptionDaily:TXO" in report
    assert "field=nasdaq" in report
    assert "field=sox" in report
    assert "module=ETF Exit; status=not_integrated" in report
