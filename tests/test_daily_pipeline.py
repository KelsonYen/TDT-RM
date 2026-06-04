import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from tdt_rm.daily_pipeline import render_report_task_summary, run_daily_pipeline

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
    assert "fallback_proxies: {}" in completed.stdout
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
    assert result["fallback_proxies"] == {}
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
    assert summary["fallback_proxies"] == {}
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
    dated_report = reports_dir / f"{LOCAL_CSV_AS_OF}_tdt_rm_daily_report.md"
    assert latest_report.exists()
    assert dated_report.exists()
    report_text = latest_report.read_text(encoding="utf-8")
    assert completed.stdout.index("TODAY'S TDT-RM MARKET RESULT") < completed.stdout.index("# TDT-RM Final Operator Report")
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
