import json
import subprocess
import sys
from pathlib import Path

TRADE_DATE = "2026-06-03"


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_valid_report(path: Path, *, include_final_decision: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sections = [
        "# TDT-RM Daily Production Report｜2026-06-03",
        "",
        "## Metadata",
        "* Trade Date: 2026-06-03",
        "",
        "## Core Model Outputs",
        "* TCWRS: 18",
        "",
        "## Provider Health Summary",
        "* price_provider: healthy",
        "",
        "## Validation Summary",
        "* validation_passed: True",
    ]
    if include_final_decision:
        sections.extend(["", "## Final Decision", "Signal: Yellow"])
    path.write_text("\n".join(sections) + "\n", encoding="utf-8")
    return path


def _valid_artifacts(tmp_path: Path, *, provider_status: str = "healthy", freshness_status: str = "passed", validation_passed: bool = True, fallback: bool = False) -> Path:
    output_dir = tmp_path / "outputs"
    _write_json(
        output_dir / "fetch_manifest.json",
        {
            "as_of": TRADE_DATE,
            "generated_at": "2026-06-03T22:00:00+00:00",
            "provider_csv_paths": {"price": str(output_dir / "price.csv")},
            "provider_health_summary": {"healthy_providers": ["price_provider"], "failed_providers": []},
            "daily_report": {"status": "passed", "report_path": str(output_dir / "daily_report.md")},
            "required_providers": ["price_provider", "breadth_provider"],
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
                    "as_of": TRADE_DATE,
                    "source_type": "live",
                    "records_loaded": 1,
                    "freshness_status": freshness_status,
                    "diagnostics": {"fallback_attempted": False},
                },
                "breadth_provider": {
                    "provider_name": "breadth_provider",
                    "status": "warning" if fallback else "healthy",
                    "as_of": TRADE_DATE,
                    "source_type": "local_fallback" if fallback else "live",
                    "records_loaded": 1,
                    "freshness_status": "passed",
                    "diagnostics": {"fallback_attempted": fallback},
                },
            },
        },
    )
    _write_json(
        output_dir / "daily_validation.json",
        {
            "trade_date": TRADE_DATE,
            "validation": {
                "status": "passed" if validation_passed else "failed",
                "passed": validation_passed,
                "blocking_errors": [] if validation_passed else ["validation gate failed"],
                "stale_data_errors": [],
            },
        },
    )
    _write_valid_report(output_dir / "daily_report.md")
    replay_dir = output_dir / "replay"
    _write_json(
        replay_dir / "replay_summary.json",
        {
            "total_days": 1,
            "successful_runs": 1,
            "failed_runs": 0,
            "status_counts": {"success": 1},
            "replay_status": "PASSED",
        },
    )
    _write_json(
        replay_dir / "replay_manifest.json",
        {
            "start_date": TRADE_DATE,
            "end_date": TRADE_DATE,
            "summary_path": str(replay_dir / "replay_summary.json"),
            "failure_log_path": str(replay_dir / "replay_failures.csv"),
        },
    )
    (replay_dir / "replay_failures.csv").write_text("date,failure_type,provider,error_message\n", encoding="utf-8")
    return output_dir


def _run_audit(output_dir: Path):
    return subprocess.run(
        [
            sys.executable,
            "scripts/production_audit.py",
            "--outputs-dir",
            str(output_dir),
            "--trade-date",
            TRADE_DATE,
            "--audit-path",
            str(output_dir / "production_audit.json"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def _audit(output_dir: Path) -> dict:
    return json.loads((output_dir / "production_audit.json").read_text(encoding="utf-8"))


def test_all_artifacts_valid_ready_exit_code_zero(tmp_path: Path):
    output_dir = _valid_artifacts(tmp_path)

    proc = _run_audit(output_dir)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    audit = _audit(output_dir)
    assert audit["status"] == "READY"
    assert all(value == "passed" for value in audit["checks"].values())


def test_missing_provider_health_not_ready_exit_code_one(tmp_path: Path):
    output_dir = _valid_artifacts(tmp_path)
    (output_dir / "provider_health.json").unlink()

    proc = _run_audit(output_dir)

    assert proc.returncode == 1
    audit = _audit(output_dir)
    assert audit["status"] == "NOT_READY"
    assert audit["checks"]["artifact_completeness"] == "failed"


def test_required_provider_failed_not_ready(tmp_path: Path):
    output_dir = _valid_artifacts(tmp_path, provider_status="failed")

    proc = _run_audit(output_dir)

    assert proc.returncode == 1
    assert _audit(output_dir)["status"] == "NOT_READY"


def test_freshness_failure_not_ready(tmp_path: Path):
    output_dir = _valid_artifacts(tmp_path, freshness_status="failed")

    proc = _run_audit(output_dir)

    assert proc.returncode == 1
    assert "failed freshness validation" in "\n".join(_audit(output_dir)["blocking_errors"])


def test_validation_failed_not_ready(tmp_path: Path):
    output_dir = _valid_artifacts(tmp_path, validation_passed=False)

    proc = _run_audit(output_dir)

    assert proc.returncode == 1
    assert _audit(output_dir)["checks"]["validation_status"] == "failed"


def test_daily_report_missing_required_section_not_ready(tmp_path: Path):
    output_dir = _valid_artifacts(tmp_path)
    _write_valid_report(output_dir / "daily_report.md", include_final_decision=False)

    proc = _run_audit(output_dir)

    assert proc.returncode == 1
    assert "daily report missing required section: Final Decision" in _audit(output_dir)["blocking_errors"]


def test_replay_summary_missing_not_ready(tmp_path: Path):
    output_dir = _valid_artifacts(tmp_path)
    (output_dir / "replay" / "replay_summary.json").unlink()

    proc = _run_audit(output_dir)

    assert proc.returncode == 1
    assert _audit(output_dir)["checks"]["replay_readiness"] == "failed"


def test_replay_failure_category_unknown_is_not_ready(tmp_path: Path):
    output_dir = _valid_artifacts(tmp_path)
    _write_json(
        output_dir / "replay" / "replay_summary.json",
        {
            "total_days": 1,
            "successful_runs": 0,
            "failed_runs": 1,
            "status_counts": {"mystery_failure": 1},
            "replay_status": "FAILED",
        },
    )
    (output_dir / "replay" / "replay_failures.csv").write_text(
        "date,failure_type,provider,error_message\n2026-06-03,mystery_failure,price_provider,nope\n",
        encoding="utf-8",
    )

    proc = _run_audit(output_dir)

    assert proc.returncode == 1
    assert "replay failure categories unknown: mystery_failure" in _audit(output_dir)["blocking_errors"]


def test_fallback_provider_warning_still_ready(tmp_path: Path):
    output_dir = _valid_artifacts(tmp_path, fallback=True)

    proc = _run_audit(output_dir)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    audit = _audit(output_dir)
    assert audit["status"] == "READY"
    assert "breadth_provider used local_fallback" in audit["warnings"]


def test_cli_output_includes_ready_and_not_ready_summary(tmp_path: Path):
    ready_output_dir = _valid_artifacts(tmp_path / "ready")
    ready_proc = _run_audit(ready_output_dir)

    not_ready_output_dir = _valid_artifacts(tmp_path / "not_ready")
    (not_ready_output_dir / "provider_health.json").unlink()
    not_ready_proc = _run_audit(not_ready_output_dir)

    assert "Production Readiness Audit" in ready_proc.stdout
    assert "Status: READY" in ready_proc.stdout
    assert "artifact_completeness: passed" in ready_proc.stdout
    assert "Production Readiness Audit" in not_ready_proc.stdout
    assert "Status: NOT_READY" in not_ready_proc.stdout
    assert "Blocking Errors:" in not_ready_proc.stdout
