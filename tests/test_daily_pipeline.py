import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from tdt_rm.daily_pipeline import run_daily_pipeline

AS_OF = "2026-05-29"
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
