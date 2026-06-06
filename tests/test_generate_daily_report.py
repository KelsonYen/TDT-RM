import json
import subprocess
import sys
from pathlib import Path

TRADE_DATE = "2026-06-03"


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _valid_artifacts(tmp_path: Path, *, provider_status: str = "healthy", provider_source_type: str = "live", provider_freshness: str = "passed", provider_as_of: str = TRADE_DATE, validation_status: str = "passed") -> Path:
    output_dir = tmp_path / "outputs"
    _write_json(
        output_dir / "fetch_manifest.json",
        {
            "as_of": TRADE_DATE,
            "generated_at": "2026-06-03T22:00:00+00:00",
            "data_status": "official",
            "pipeline_status": "passed",
            "failed_sources": [],
            "stale_sources": [],
            "required_providers": ["price_provider", "leadership_provider", "breadth_provider"],
        },
    )
    _write_json(
        output_dir / "provider_health.json",
        {
            "as_of": TRADE_DATE,
            "providers": {
                "price_provider": {
                    "provider_name": "price_provider",
                    "status": provider_status,
                    "as_of": provider_as_of,
                    "source_type": provider_source_type,
                    "records_loaded": 1,
                    "freshness_status": provider_freshness,
                    "diagnostics": {"messages": ["provider used local fallback"] if provider_source_type == "local_fallback" else []},
                },
                "leadership_provider": {
                    "provider_name": "leadership_provider",
                    "status": "healthy",
                    "as_of": TRADE_DATE,
                    "source_type": "live",
                    "records_loaded": 7,
                    "freshness_status": "passed",
                },
                "breadth_provider": {
                    "provider_name": "breadth_provider",
                    "status": "warning" if provider_source_type == "local_fallback" else "healthy",
                    "as_of": TRADE_DATE,
                    "source_type": provider_source_type if provider_source_type == "local_fallback" else "live",
                    "records_loaded": 1,
                    "freshness_status": "passed",
                    "diagnostics": {"messages": ["breadth provider used fallback"]} if provider_source_type == "local_fallback" else {},
                },
            },
        },
    )
    _write_json(
        output_dir / f"tdt_rm_daily_{TRADE_DATE}.json",
        {
            "trade_date": TRADE_DATE,
            "timestamp": "2026-06-03T22:30:00+00:00",
            "model_version": "TDT-RM V5.1.4 Backtest Calibration Patch",
            "data": {"latest_bar_date": TRADE_DATE, "data_status": "official"},
            "scores": {"TCWRS": 18, "MHS": 76, "ETI-5": 0, "Tail Risk": 32, "BCD": 28, "CP": 24.8},
            "market_regime": "Hot",
            "signal": "Yellow",
            "equity_exposure_limit": "60-80%",
            "tcwrs": 18,
            "mhs": 76,
            "eti_5": 0,
            "tail_risk": 32,
            "bcd": 28,
            "cp": 24.8,
        },
    )
    _write_json(
        output_dir / f"tdt_rm_daily_{TRADE_DATE}_manifest.json",
        {
            "trade_date": TRADE_DATE,
            "model_version": "TDT-RM V5.1.4 Backtest Calibration Patch",
            "data_status": "official",
            "validation_status": validation_status,
            "validation": {"status": validation_status, "passed": validation_status in {"passed", "warning"}, "errors": [], "warnings": []},
            "artifact_paths": {
                "json": str(output_dir / f"tdt_rm_daily_{TRADE_DATE}.json"),
                "markdown": str(output_dir / f"tdt_rm_daily_{TRADE_DATE}.md"),
            },
        },
    )
    return output_dir


def _run(output_dir: Path):
    return subprocess.run(
        [
            sys.executable,
            "scripts/generate_daily_report.py",
            "--trade-date",
            TRADE_DATE,
            "--outputs-dir",
            str(output_dir),
            "--report-path",
            str(output_dir / "daily_report.md"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def test_valid_full_output_artifacts_generate_daily_report(tmp_path: Path):
    output_dir = _valid_artifacts(tmp_path)

    proc = _run(output_dir)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = (output_dir / "daily_report.md").read_text(encoding="utf-8")
    assert report.splitlines()[0] == "2026/06/03 台股雙溫度計風控報告"
    assert "TCWRS：18" in report
    assert "Crash Probability：24.8%" in report
    assert "今日燈號：黃燈" in report


def test_missing_model_output_fails_closed_without_formal_report(tmp_path: Path):
    output_dir = _valid_artifacts(tmp_path)
    (output_dir / f"tdt_rm_daily_{TRADE_DATE}.json").unlink()

    proc = _run(output_dir)

    assert proc.returncode != 0
    assert not (output_dir / "daily_report.md").exists()
    failed = (output_dir / "daily_report_failed.md").read_text(encoding="utf-8")
    assert "PRODUCTION REPORT FAILED" in failed
    assert "NOT FOR TRADING USE" in failed


def test_validation_failed_fails_closed(tmp_path: Path):
    output_dir = _valid_artifacts(tmp_path, validation_status="failed")

    proc = _run(output_dir)

    assert proc.returncode != 0
    assert not (output_dir / "daily_report.md").exists()


def test_provider_failed_fails_closed(tmp_path: Path):
    output_dir = _valid_artifacts(tmp_path, provider_status="failed")

    proc = _run(output_dir)

    assert proc.returncode != 0
    assert not (output_dir / "daily_report.md").exists()


def test_stale_as_of_fails_closed(tmp_path: Path):
    output_dir = _valid_artifacts(tmp_path, provider_as_of="2026-06-02")

    proc = _run(output_dir)

    assert proc.returncode != 0
    assert "does not match trade_date" in proc.stderr
    assert not (output_dir / "daily_report.md").exists()


def test_provider_fallback_warning_still_generates_report(tmp_path: Path):
    output_dir = _valid_artifacts(tmp_path, provider_status="warning", provider_source_type="local_fallback")

    proc = _run(output_dir)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = (output_dir / "daily_report.md").read_text(encoding="utf-8")
    forbidden = ["Audit", "Pipeline", "Validation", "Artifact", "canonical artifact", "source artifact"]
    assert all(term not in report for term in forbidden)
    assert "今日動作" in report


def test_generated_report_includes_all_required_sections(tmp_path: Path):
    output_dir = _valid_artifacts(tmp_path)

    proc = _run(output_dir)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = (output_dir / "daily_report.md").read_text(encoding="utf-8")
    for section in ["核心結論", "ETI-5明細", "今日動作", "優先減碼順序", "警報解除條件", "結論"]:
        assert f"■ {section}" in report


def test_manifest_records_report_generation_status(tmp_path: Path):
    output_dir = _valid_artifacts(tmp_path)

    proc = _run(output_dir)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    fetch_manifest = json.loads((output_dir / "fetch_manifest.json").read_text(encoding="utf-8"))
    production_manifest = json.loads((output_dir / f"tdt_rm_daily_{TRADE_DATE}_manifest.json").read_text(encoding="utf-8"))
    assert fetch_manifest["daily_report"]["status"] == "passed"
    assert fetch_manifest["daily_report"]["report_path"] == str(output_dir / "daily_report.md")
    assert production_manifest["daily_report"]["status"] == "passed"


def test_user_report_format_quality_requirements(tmp_path: Path):
    output_dir = _valid_artifacts(tmp_path)

    proc = _run(output_dir)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = (output_dir / "daily_report.md").read_text(encoding="utf-8")
    forbidden = [
        "Audit",
        "Pipeline",
        "Validation",
        "Artifact",
        "canonical artifact",
        "source artifact",
        "manifest",
        "provider attempts",
        "fallback dependencies",
        "operator quality gate",
        "Production Report Quality",
        "FAIL_FOR_OPERATOR_USE",
        "PASS_FOR_OPERATOR_USE",
    ]
    assert all(term not in report for term in forbidden)
    assert report.splitlines()[0] == "2026/06/03 台股雙溫度計風控報告"
    assert all(f"■ {section}" in report for section in ["核心結論", "ETI-5明細", "今日動作", "優先減碼順序", "警報解除條件", "結論"])
    assert "|" not in report
    assert "今日燈號" in report
    assert "股票曝險上限" in report
    assert "■ 今日動作" in report
    assert all(label in report for label in [
        "ETI-1 加權指數跌破20日線",
        "ETI-2 外資連續賣超",
        "ETI-3 新台幣轉貶",
        "ETI-4 市場廣度惡化",
        "ETI-5 主流七標的失靈",
    ])
    assert "產出時間：" in report
    assert __import__("re").search(r"產出時間：\d{4}/\d{2}/\d{2} \d{2}:\d{2}", report)
    assert __import__("re").search(r"資料狀態：(正式版|暫估版)", report)
