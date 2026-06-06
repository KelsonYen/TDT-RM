import json
from datetime import date
from pathlib import Path

from tdt_rm.daily_pipeline import render_final_operator_report, run_daily_pipeline
from tdt_rm.daily_validation import validate_daily_artifacts
from tdt_rm.report_quality import assess_production_report_quality, render_operator_disclosure


TRADE_DATE = date(2026, 6, 5)
INPUT_DIR = Path("inputs/daily/2026-06-05")


def test_2026_06_05_confirmed_finmind_and_unavailable_global_risk_pass_operator_quality(tmp_path: Path):
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
    assert payload["production_report_quality"] == "PASS"
    assert result["production_report_quality"] == "PASS"
    assert disclosure["acceptable_for_real_world_daily_use"] is True
    assert disclosure["blocking_reasons"] == []
    assert disclosure["fallback_provider_datasets"] == []
    assert disclosure["fallback_operator_dependencies"] == []
    assert disclosure["placeholder_default_like_fields"] == []
    assert set(payload["data"]["unavailable_global_risk_fields"]) >= {"nasdaq", "sox"}
    assert payload["data"]["global_risk_calculation_status"] == "unavailable_source_fields_excluded"
    assert "required module(s) not integrated: ETF Exit" not in disclosure["blocking_reasons"]
    assert any(item["module"] == "ETF Exit" and item["status"] == "not_integrated" for item in disclosure["non_integrated_modules"])
    assert any(item["module"] == "ETF Exit" and item["status"] == "not_integrated" for item in disclosure["non_blocking_module_warnings"])

    report = render_final_operator_report(result)
    assert report.splitlines()[0] == "2026/06/05 台股雙溫度計風控報告"
    assert "今日燈號：黃燈" in report
    assert "股票曝險上限：60–80%" in report
    assert "Audit" not in report and "Pipeline" not in report and "Validation" not in report
    assert "field=nasdaq" not in report
    assert "field=sox" not in report
    assert "required module(s) not integrated: ETF Exit" not in report


def test_etf_exit_not_integrated_only_passes_with_non_blocking_disclosure():
    payload = {"etf_exit": {"status": "not_integrated", "notes": "standalone daily report"}, "data": {}}

    disclosure = assess_production_report_quality(payload)

    assert disclosure["production_report_quality"] == "PASS"
    assert disclosure["acceptable_for_real_world_daily_use"] is True
    assert disclosure["blocking_reasons"] == []
    assert disclosure["non_integrated_modules"] == [
        {"module": "ETF Exit", "status": "not_integrated", "notes": "standalone daily report"}
    ]
    assert disclosure["non_blocking_module_warnings"] == disclosure["non_integrated_modules"]

    rendered = render_operator_disclosure(disclosure)
    blocking_section, rest = rendered.split("### Non-Blocking Module Warnings", maxsplit=1)
    module_section = rest.split("### Data-Source Warnings", maxsplit=1)[0]
    assert "required module(s) not integrated: ETF Exit" not in rendered
    assert "module=ETF Exit; status=not_integrated" not in blocking_section
    assert "module=ETF Exit; status=not_integrated" in module_section


def test_options_csv_bcd_source_fails_even_for_confirmed_finmind_provider():
    payload = {
        "data": {
            "field_sources": {"tail_risk": "options_csv", "bcd": "options_csv"},
            "source_metadata": {
                "options_csv": {
                    "provider_source": "FINMIND_FALLBACK:TaiwanOptionDaily:TXO",
                    "source_type": "REAL_PROVIDER",
                    "name": "Local options CSV",
                }
            },
        }
    }

    disclosure = assess_production_report_quality(payload)

    assert disclosure["production_report_quality"] == "FAIL_FOR_OPERATOR_USE"
    assert disclosure["fallback_provider_datasets"] == []
    assert disclosure["fallback_operator_dependencies"] == []
    assert disclosure["bcd_provider_violations"] == [
        {"field": "field_sources.bcd", "source_id": "options_csv", "reason": "field_sources.bcd == options_csv"}
    ]
    assert disclosure["blocking_reasons"] == ["provider-supplied BCD is forbidden: field_sources.bcd == options_csv"]


def test_nasdaq_sox_zero_without_source_fails():
    payload = {
        "data": {"field_sources": {}, "source_metadata": {}},
        "traces": {"tcwrs": {"factors": {"G": {"conditions": {"raw": {"nasdaq": 0.0, "sox": 0.0}}}}}},
    }

    disclosure = assess_production_report_quality(payload)

    assert disclosure["production_report_quality"] == "FAIL_FOR_OPERATOR_USE"
    assert disclosure["acceptable_for_real_world_daily_use"] is False
    assert {item["field"] for item in disclosure["placeholder_default_like_fields"]} == {"nasdaq", "sox"}
    assert disclosure["blocking_reasons"] == ["default-like global-risk field(s) without confirmed source: nasdaq, sox"]


def test_nasdaq_sox_unavailable_without_operator_calculation_is_acceptable():
    payload = {
        "data": {
            "field_sources": {},
            "source_metadata": {},
            "unavailable_global_risk_fields": ["nasdaq", "sox"],
            "global_risk_calculation_status": "unavailable_source_fields_excluded",
        },
        "traces": {"tcwrs": {"factors": {"G": {"conditions": {"raw": {"nasdaq": 0.0, "sox": 0.0}}}}}},
    }

    disclosure = assess_production_report_quality(payload)

    assert disclosure["production_report_quality"] == "PASS"
    assert disclosure["acceptable_for_real_world_daily_use"] is True
    assert disclosure["placeholder_default_like_fields"] == []
    assert disclosure["blocking_reasons"] == []


def test_production_report_quality_fails_only_with_blocking_reasons():
    clean = assess_production_report_quality({"data": {}})
    blocked = assess_production_report_quality(
        {"data": {"field_sources": {}, "source_metadata": {}}, "inputs": {"nasdaq": 0.0, "sox": 0.0}}
    )

    assert clean["blocking_reasons"] == []
    assert clean["production_report_quality"] == "PASS"
    assert blocked["blocking_reasons"]
    assert blocked["production_report_quality"] == "FAIL_FOR_OPERATOR_USE"


def test_production_report_explains_bcd_or_data_limits(tmp_path: Path):
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

    report = render_final_operator_report(result)

    assert "BCD：資料不足／INCOMPLETE" in report
    assert "BCD 資料不足，未納入升燈判斷，不影響 TCWRS、ETI-5、Tail Risk 與今日燈號。" in report
    assert "Missing Inputs" not in report
    assert "BCD Status" not in report
