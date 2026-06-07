import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from tdt_rm.daily_pipeline import (
    detect_duplicate_operator_artifact_families,
    render_report_task_summary,
    run_daily_pipeline,
    validate_operator_report_canonical_sources,
    write_final_operator_reports,
    write_json_summary,
)

AS_OF = "2026-05-29"
LOCAL_CSV_AS_OF = "2026-06-03"
LOCAL_CSV_DIR = Path("inputs/daily/2026-06-03")
REQUIRED_LOCAL_CSVS = ("price.csv", "foreign_flow.csv", "fx.csv", "breadth.csv", "futures.csv", "options.csv", "leadership.csv", "margin.csv")
PROVIDER_DIR = Path("examples/provider_inputs")
SNAPSHOT_FIXTURE = Path("examples/daily_snapshots/sample_enriched_snapshot.json")


def provider_args(output_dir: Path) -> list[str]:
    return [
        sys.executable,
        "scripts/run_daily_pipeline.py",
        "--as-of",
        AS_OF,
        "--price-csv",
        str(PROVIDER_DIR / "sample_price.csv"),
        "--foreign-csv",
        str(PROVIDER_DIR / "sample_foreign_flow.csv"),
        "--fx-csv",
        str(PROVIDER_DIR / "sample_fx.csv"),
        "--breadth-csv",
        str(PROVIDER_DIR / "sample_breadth.csv"),
        "--leadership-csv",
        str(PROVIDER_DIR / "sample_leadership.csv"),
        "--scores-csv",
        str(PROVIDER_DIR / "sample_scores.csv"),
        "--field-map",
        str(PROVIDER_DIR / "sample_provider_field_map.json"),
        "--output-dir",
        str(output_dir),
        "--allow-warnings",
    ]


def test_canonical_report_source_consistency_guard_rejects_mismatched_summary(tmp_path: Path):
    result = {
        "trade_date": AS_OF,
        "artifact_paths": {"json": str(tmp_path / "canonical.json"), "manifest": str(tmp_path / "canonical_manifest.json")},
    }
    summary_path = tmp_path / "pipeline_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "trade_date": AS_OF,
                "artifact_paths": {"json": str(tmp_path / "other.json"), "manifest": str(tmp_path / "canonical_manifest.json")},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="canonical source guard mismatch for artifact_paths.json"):
        validate_operator_report_canonical_sources(result, summary_path)


def test_no_staging_artifact_as_operator_source_guard(tmp_path: Path):
    staging_json = tmp_path / "inputs" / AS_OF / "_strict_provider_csvs" / f"tdt_rm_daily_{AS_OF}.json"
    staging_manifest = staging_json.with_name(f"tdt_rm_daily_{AS_OF}_manifest.json")
    result = {"trade_date": AS_OF, "artifact_paths": {"json": str(staging_json), "manifest": str(staging_manifest)}}
    summary_path = tmp_path / "pipeline_summary.json"
    summary_path.write_text(json.dumps(result), encoding="utf-8")

    with pytest.raises(ValueError, match="rejected staging artifact as operator source"):
        validate_operator_report_canonical_sources(result, summary_path)


def test_duplicate_artifact_family_detection(tmp_path: Path):
    first = tmp_path / "outputs" / AS_OF
    second = tmp_path / "reports" / AS_OF / "artifacts"
    for root in (first, second):
        root.mkdir(parents=True)
        (root / f"tdt_rm_daily_{AS_OF}.json").write_text("{}", encoding="utf-8")
        (root / f"tdt_rm_daily_{AS_OF}_manifest.json").write_text("{}", encoding="utf-8")
        (root / "pipeline_summary.json").write_text("{}", encoding="utf-8")

    families = detect_duplicate_operator_artifact_families(AS_OF, (tmp_path / "outputs", tmp_path / "reports"))

    assert {Path(family["root"]).name for family in families} == {AS_OF, "artifacts"}
    assert len(families) == 2


def test_2026_06_05_canonical_regression_values_and_input_source(tmp_path: Path):
    trade_date = "2026-06-05"
    input_dir = Path("inputs/daily") / trade_date
    output_dir = tmp_path / "outputs" / trade_date
    reports_dir = tmp_path / "reports" / trade_date
    summary_path = output_dir / "pipeline_summary.json"

    result = run_daily_pipeline(
        as_of=date.fromisoformat(trade_date),
        output_dir=output_dir,
        price_csv=input_dir / "price.csv",
        foreign_csv=input_dir / "foreign_flow.csv",
        fx_csv=input_dir / "fx.csv",
        breadth_csv=input_dir / "breadth.csv",
        futures_csv=input_dir / "futures.csv",
        options_csv=input_dir / "options.csv",
        leadership_csv=input_dir / "leadership.csv",
        margin_csv=input_dir / "margin.csv",
        command="pytest",
    )
    write_json_summary(result, summary_path)
    write_final_operator_reports(result, reports_dir, pipeline_summary_path=summary_path)

    payload = json.loads(Path(result["artifact_paths"]["json"]).read_text(encoding="utf-8"))
    report = (reports_dir / f"{trade_date}_tdt_rm_user_report.md").read_text(encoding="utf-8")

    assert result["production_report_quality"] == "PASS"
    assert result["operator_disclosure"]["acceptable_for_real_world_daily_use"] is True
    assert result["scores"]["MHS"] == 100.0
    assert result["scores"]["TCWRS"] == 12
    assert result["scores"]["ETI-5"] == 1
    assert result["scores"]["Tail Risk"] == 53.95
    assert result["scores"]["BCD"] is None
    assert result["scores"]["CP"] == 21.59
    assert result["fallback_proxies"]["bcd"]["status"] == "incomplete_bcd"
    
    assert result["signal"] == "Yellow"
    assert result["exposure_limit"] == "60-80%"
    assert payload["operator_disclosure"]["acceptable_for_real_world_daily_use"] is True
    assert report.splitlines()[0] == "2026/06/05 台股雙溫度計風控報告"
    assert "今日燈號：黃燈" in report
    assert "股票曝險上限：60–80%" in report
    assert "ETI Audit Trace Available: PASS" in report
    assert "Pipeline" not in report and "Artifact" not in report


def test_quality_gate_freshness_uses_selected_pipeline_summary(tmp_path: Path):
    trade_date = AS_OF
    output_dir = tmp_path / "outputs" / trade_date
    output_dir.mkdir(parents=True)
    result = {
        "trade_date": trade_date,
        "latest_bar_date": trade_date,
        "validation_status": "passed",
        "data_status": "enriched_snapshot",
        "production_report_quality": "PASS",
        "operator_disclosure": {"production_report_quality": "PASS", "acceptable_for_real_world_daily_use": True},
        "scores": {"TCWRS": 12, "MHS": 100.0, "ETI-5": 1, "Tail Risk": 53.95, "BCD": 53.95, "CP": 26.98},
        "signal": "Yellow",
        "exposure_limit": "60-80%",
        "artifact_paths": {
            "json": str(output_dir / f"tdt_rm_daily_{trade_date}.json"),
            "manifest": str(output_dir / f"tdt_rm_daily_{trade_date}_manifest.json"),
        },
        "validation": {},
    }
    summary_path = output_dir / "pipeline_summary.json"
    write_json_summary(result, summary_path)

    paths = write_final_operator_reports(result, tmp_path / "reports" / trade_date, pipeline_summary_path=summary_path)

    report = paths["dated"].read_text(encoding="utf-8")
    assert paths["dated"].name == f"{trade_date}_tdt_rm_user_report.md"
    assert report.splitlines()[0] == f"{trade_date.replace('-', '/')} 台股雙溫度計風控報告"
    assert "股票曝險上限：60–80%" in report
    assert "Report Quality Gate" in report and "Manifest" not in report


def test_pipeline_runs_from_provider_fixture_csvs_and_writes_artifacts(tmp_path: Path):
    output_dir = tmp_path / "daily"
    completed = subprocess.run(provider_args(output_dir), check=False, capture_output=True, text=True)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "trade_date: 2026-05-29" in completed.stdout
    assert "data_status: enriched_snapshot" in completed.stdout
    assert "signal:" in completed.stdout
    assert "exposure_limit:" in completed.stdout
    assert "TCWRS:" in completed.stdout
    assert "MHS:" in completed.stdout
    assert "ETI-5:" in completed.stdout
    assert "available_eti_components:" in completed.stdout
    assert "Tail Risk:" in completed.stdout
    assert "BCD:" in completed.stdout
    assert "CP:" in completed.stdout
    assert "incomplete_bcd" in completed.stdout
    assert "provider_warnings:" in completed.stdout
    assert "validation_status: passed" in completed.stdout
    assert (output_dir / "tdt_rm_daily_2026-05-29.json").exists()
    assert (output_dir / "tdt_rm_daily_2026-05-29.md").exists()
    assert (output_dir / "tdt_rm_daily_2026-05-29_manifest.json").exists()
    assert (output_dir / "assembled_daily_snapshot_2026-05-29.json").exists()


def test_pipeline_runs_from_existing_snapshot_json(tmp_path: Path):
    output_dir = tmp_path / "snapshot"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_daily_pipeline.py",
            "--as-of",
            AS_OF,
            "--snapshot-path",
            str(SNAPSHOT_FIXTURE),
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "assembled_snapshot: examples/daily_snapshots/sample_enriched_snapshot.json" in completed.stdout
    assert (output_dir / "tdt_rm_daily_2026-05-29.json").exists()
    assert (output_dir / "tdt_rm_daily_2026-05-29.md").exists()
    assert (output_dir / "tdt_rm_daily_2026-05-29_manifest.json").exists()
    assert not (output_dir / "assembled_daily_snapshot_2026-05-29.json").exists()


def test_snapshot_out_and_summary_surface_available_eti_and_no_fallbacks(tmp_path: Path):
    snapshot_out = tmp_path / "custom" / "assembled.json"

    result = run_daily_pipeline(
        as_of=date.fromisoformat(AS_OF),
        output_dir=tmp_path / "daily",
        snapshot_out=snapshot_out,
        price_csv=PROVIDER_DIR / "sample_price.csv",
        foreign_csv=PROVIDER_DIR / "sample_foreign_flow.csv",
        fx_csv=PROVIDER_DIR / "sample_fx.csv",
        breadth_csv=PROVIDER_DIR / "sample_breadth.csv",
        leadership_csv=PROVIDER_DIR / "sample_leadership.csv",
        scores_csv=PROVIDER_DIR / "sample_scores.csv",
        field_map=PROVIDER_DIR / "sample_provider_field_map.json",
    )

    assert snapshot_out.exists()
    assert result["assembled_snapshot_path"] == str(snapshot_out)
    assert result["fallback_proxies"]["bcd"]["status"] == "incomplete_bcd"
    assert set(result["available_eti_components"]) == {"ETI-1", "ETI-2", "ETI-3", "ETI-4", "ETI-5"}
    assert result["validation_status"] == "passed"


def test_pipeline_exits_nonzero_on_missing_required_price_csv(tmp_path: Path):
    completed = subprocess.run(
        [sys.executable, "scripts/run_daily_pipeline.py", "--as-of", AS_OF, "--output-dir", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "--price-csv is required unless --snapshot-path is supplied" in completed.stderr


def test_no_manifest_suppresses_manifest_artifact(tmp_path: Path):
    output_dir = tmp_path / "daily"
    completed = subprocess.run(provider_args(output_dir) + ["--no-manifest"], check=False, capture_output=True, text=True)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert (output_dir / "tdt_rm_daily_2026-05-29.json").exists()
    assert (output_dir / "tdt_rm_daily_2026-05-29.md").exists()
    assert not (output_dir / "tdt_rm_daily_2026-05-29_manifest.json").exists()
    assert "  manifest:" not in completed.stdout


def test_json_summary_writes_machine_readable_summary(tmp_path: Path):
    output_dir = tmp_path / "daily"
    summary_path = tmp_path / "summary.json"
    completed = subprocess.run(provider_args(output_dir) + ["--json-summary", str(summary_path)], check=False, capture_output=True, text=True)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["trade_date"] == AS_OF
    assert summary["validation_status"] == "passed"
    assert summary["artifact_paths"]["json"] == str(output_dir / "tdt_rm_daily_2026-05-29.json")
    assert summary["fallback_proxies"]["bcd"]["status"] == "incomplete_bcd"
    assert set(summary["available_eti_components"]) == {"ETI-1", "ETI-2", "ETI-3", "ETI-4", "ETI-5"}


def test_production_pipeline_writes_latest_report_and_prints_full_task_summary(tmp_path: Path):
    inputs_dir = _copy_strict_local_csvs(tmp_path / "inputs")
    output_dir = tmp_path / "daily"
    reports_dir = tmp_path / "reports"
    summary_path = output_dir / "pipeline_summary.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_daily_production_pipeline.py",
            "--trade-date",
            LOCAL_CSV_AS_OF,
            "--inputs-dir",
            str(inputs_dir),
            "--outputs-dir",
            str(output_dir),
            "--pipeline-summary",
            str(summary_path),
            "--reports-dir",
            str(reports_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    latest_report = reports_dir / "latest_report.md"
    dated_report = reports_dir / f"{LOCAL_CSV_AS_OF}_tdt_rm_user_report.md"
    assert latest_report.exists()
    assert dated_report.exists()
    report_text = latest_report.read_text(encoding="utf-8")
    assert completed.stdout.index("TODAY'S TDT-RM MARKET RESULT") < completed.stdout.index(f"{LOCAL_CSV_AS_OF.replace('-', '/')} 台股雙溫度計風控報告")
    assert f"Data Date: {LOCAL_CSV_AS_OF}" in completed.stdout
    assert "Signal:" in completed.stdout
    assert "Regime State:" in completed.stdout
    assert "TCWRS:" in completed.stdout
    assert "MHS:" in completed.stdout
    assert "ETI-5:" in completed.stdout
    assert "Tail Risk:" in completed.stdout
    assert "BCD:" in completed.stdout
    assert "Crash Probability:" in completed.stdout
    assert "Exposure Limit:" in completed.stdout
    assert "Recommended Action:" in completed.stdout
    assert report_text in completed.stdout


def test_production_pipeline_fails_closed_when_required_local_csv_is_missing(tmp_path: Path):
    inputs_dir = _copy_strict_local_csvs(tmp_path / "inputs")
    (inputs_dir / "options.csv").unlink()

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_daily_production_pipeline.py",
            "--trade-date",
            LOCAL_CSV_AS_OF,
            "--inputs-dir",
            str(inputs_dir),
            "--outputs-dir",
            str(tmp_path / "daily"),
            "--reports-dir",
            str(tmp_path / "reports"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "daily input CSV validation failed" in completed.stderr
    assert f"missing required CSV: {inputs_dir / 'options.csv'}" in completed.stderr
    assert not (tmp_path / "daily" / f"tdt_rm_daily_{LOCAL_CSV_AS_OF}.json").exists()


def test_production_pipeline_runs_from_local_csvs_with_blocked_network_env(tmp_path: Path):
    inputs_dir = _copy_strict_local_csvs(tmp_path / "inputs")
    env = {
        **os.environ,
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "ALL_PROXY": "http://127.0.0.1:9",
    }

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_daily_production_pipeline.py",
            "--trade-date",
            LOCAL_CSV_AS_OF,
            "--inputs-dir",
            str(inputs_dir),
            "--outputs-dir",
            str(tmp_path / "daily"),
            "--pipeline-summary",
            str(tmp_path / "daily" / "pipeline_summary.json"),
            "--reports-dir",
            str(tmp_path / "reports"),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "validation_status: passed" in completed.stdout
    assert (tmp_path / "daily" / f"tdt_rm_daily_{LOCAL_CSV_AS_OF}.json").exists()


def test_missing_latest_report_summary_fails_with_generation_command(tmp_path: Path):
    missing_report = tmp_path / "reports" / "latest_report.md"

    with pytest.raises(FileNotFoundError) as excinfo:
        render_report_task_summary(missing_report, {"trade_date": AS_OF})

    message = str(excinfo.value)
    assert str(missing_report) in message
    assert (
        "python scripts/run_daily_production_pipeline.py --trade-date 2026-05-29 "
        "--inputs-dir inputs/daily/2026-05-29 --outputs-dir outputs/daily "
        "--pipeline-summary outputs/daily/tdt_rm_daily_2026-05-29_summary.json"
    ) in message


def _copy_strict_local_csvs(destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    for filename in REQUIRED_LOCAL_CSVS:
        target = destination / filename
        source = LOCAL_CSV_DIR / filename
        if source.exists():
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            continue
        if filename == "margin.csv":
            target.write_text(
                "trade_date,provider_source,source_type,margin_balance_5d_flat_or_down,hot_stock_margin_fast_increase,margin_balance_5d_increases,index_5d_return_pct,margin_balance_5d_decline_pct,margin_not_retreating\n"
                f"{LOCAL_CSV_AS_OF},TWSE_margin_test_fixture,official_manual,true,false,false,1.25,0.4,false\n",
                encoding="utf-8",
            )
            continue
        raise FileNotFoundError(source)
    return destination
