from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest


def load_replay_module():
    path = Path("scripts/replay_daily_pipeline.py").resolve()
    spec = importlib.util.spec_from_file_location("replay_daily_pipeline", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_price_csv(path: Path, dates: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["date", "taiex_close", "taiex_ma5", "taiex_ma20", "taiex_ma60", "taiex_ma20_slope", "turnover_amount"],
        )
        writer.writeheader()
        for index, day in enumerate(dates):
            close = 42100 + index
            writer.writerow(
                {
                    "date": day,
                    "taiex_close": close,
                    "taiex_ma5": close - 5,
                    "taiex_ma20": close - 20,
                    "taiex_ma60": close - 60,
                    "taiex_ma20_slope": 35,
                    "turnover_amount": 520000000000,
                }
            )


def write_source_config(path: Path, price_csv: Path, *, max_lag_days: int = 0) -> Path:
    payload = {
        "sources": [
            {
                "source_id": "historical_price_fixture",
                "source_name": "Historical price fixture",
                "provider_category": "price",
                "adapter": "local_price_fallback",
                "source_type": "local_csv_fallback",
                "enabled": True,
                "fallback_order": 10,
                "path": str(price_csv),
                "freshness_rules": {"max_lag_days": max_lag_days},
            }
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def run_replay(tmp_path: Path, start: str, end: str, config: Path) -> tuple[subprocess.CompletedProcess[str], Path]:
    output_dir = tmp_path / "replay"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/replay_daily_pipeline.py",
            "--start-date",
            start,
            "--end-date",
            end,
            "--outputs-dir",
            str(output_dir),
            "--source-config",
            str(config),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed, output_dir


def test_single_day_replay_success(tmp_path: Path):
    price_csv = tmp_path / "price.csv"
    write_price_csv(price_csv, ["2026-05-29"])
    config = write_source_config(tmp_path / "sources.json", price_csv)

    completed, output_dir = run_replay(tmp_path, "2026-05-29", "2026-05-29", config)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    summary = json.loads((output_dir / "replay_summary.json").read_text(encoding="utf-8"))
    assert summary["total_days"] == 1
    assert summary["successful_runs"] == 1
    assert summary["failed_runs"] == 0
    assert (output_dir / "2026-05-29" / "providers" / "provider_health.json").exists()
    assert (output_dir / "2026-05-29" / "daily" / "tdt_rm_daily_2026-05-29.json").exists()


def test_multi_day_replay_success(tmp_path: Path):
    price_csv = tmp_path / "price.csv"
    write_price_csv(price_csv, ["2026-05-29", "2026-05-30"])
    config = write_source_config(tmp_path / "sources.json", price_csv)

    completed, output_dir = run_replay(tmp_path, "2026-05-29", "2026-05-30", config)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    summary = json.loads((output_dir / "replay_summary.json").read_text(encoding="utf-8"))
    assert summary["total_days"] == 2
    assert summary["successful_runs"] == 2
    assert summary["failed_runs"] == 0


def test_provider_failure_correctly_logged(tmp_path: Path):
    config = tmp_path / "sources.json"
    config.write_text(json.dumps({"sources": []}), encoding="utf-8")

    completed, output_dir = run_replay(tmp_path, "2026-05-29", "2026-05-29", config)

    assert completed.returncode == 1
    failures = list(csv.DictReader((output_dir / "replay_failures.csv").open(encoding="utf-8")))
    assert failures[0]["failure_type"] == "provider_failure"
    assert failures[0]["provider"] == "price_provider"


def test_freshness_failure_correctly_logged(tmp_path: Path):
    price_csv = tmp_path / "price.csv"
    write_price_csv(price_csv, ["2026-05-29"])
    config = write_source_config(tmp_path / "sources.json", price_csv, max_lag_days=0)

    completed, output_dir = run_replay(tmp_path, "2026-05-30", "2026-05-30", config)

    assert completed.returncode == 1
    failures = list(csv.DictReader((output_dir / "replay_failures.csv").open(encoding="utf-8")))
    assert failures[0]["failure_type"] == "freshness_failure"
    assert "stale" in failures[0]["error_message"]



def _dated_provider_fixture(tmp_path: Path, day: str) -> Path:
    root = tmp_path / "provider_inputs"
    day_dir = root / day
    day_dir.mkdir(parents=True, exist_ok=True)
    write_price_csv(day_dir / "price.csv", [day])
    return root

def test_validation_failure_correctly_logged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    replay = load_replay_module()

    def fake_pipeline(**kwargs):
        return {
            "validation": {"has_errors": True, "error_count": 1, "issues": [{"severity": "error", "code": "invalid_json_payload", "message": "validation gate failed"}]},
            "artifact_paths": {},
        }

    monkeypatch.setattr(replay, "run_daily_pipeline", fake_pipeline)
    result = replay.replay_one_day(
        as_of=date(2026, 5, 29),
        outputs_dir=tmp_path,
        registry=replay.PublicDataFetcherRegistry.from_config({"sources": []}),
        source_config={"sources": []},
        main7_symbols=(),
        cache_dir=None,
        provider_inputs_dir=_dated_provider_fixture(tmp_path, "2026-05-29"),
        snapshots_dir=None,
    )

    assert result.status == "validation_failure"
    assert result.failure.failure_type == "validation_failure"


def test_report_failure_correctly_logged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    replay = load_replay_module()

    def fake_pipeline(**kwargs):
        return {
            "validation": {"has_errors": True, "error_count": 1, "issues": [{"severity": "error", "code": "missing_markdown_artifact", "message": "daily_report missing required field"}]},
            "artifact_paths": {},
        }

    monkeypatch.setattr(replay, "run_daily_pipeline", fake_pipeline)
    result = replay.replay_one_day(
        as_of=date(2026, 5, 29),
        outputs_dir=tmp_path,
        registry=replay.PublicDataFetcherRegistry.from_config({"sources": []}),
        source_config={"sources": []},
        main7_symbols=(),
        cache_dir=None,
        provider_inputs_dir=_dated_provider_fixture(tmp_path, "2026-05-29"),
        snapshots_dir=None,
    )

    assert result.status == "report_generation_failure"
    assert result.failure.provider == "validation_gate"


def test_replay_summary_json_generated(tmp_path: Path):
    price_csv = tmp_path / "price.csv"
    write_price_csv(price_csv, ["2026-05-29"])
    config = write_source_config(tmp_path / "sources.json", price_csv)

    completed, output_dir = run_replay(tmp_path, "2026-05-29", "2026-05-29", config)

    assert completed.returncode == 0
    assert (output_dir / "replay_summary.json").exists()


def test_replay_failures_csv_generated(tmp_path: Path):
    price_csv = tmp_path / "price.csv"
    write_price_csv(price_csv, ["2026-05-29"])
    config = write_source_config(tmp_path / "sources.json", price_csv)

    completed, output_dir = run_replay(tmp_path, "2026-05-29", "2026-05-29", config)

    assert completed.returncode == 0
    assert (output_dir / "replay_failures.csv").read_text(encoding="utf-8").startswith("date,failure_type,provider,error_message")


def test_replay_manifest_json_generated(tmp_path: Path):
    price_csv = tmp_path / "price.csv"
    write_price_csv(price_csv, ["2026-05-29"])
    config = write_source_config(tmp_path / "sources.json", price_csv)

    completed, output_dir = run_replay(tmp_path, "2026-05-29", "2026-05-29", config)

    assert completed.returncode == 0
    manifest = json.loads((output_dir / "replay_manifest.json").read_text(encoding="utf-8"))
    assert manifest["summary_path"] == str(output_dir / "replay_summary.json")
    assert manifest["failure_log_path"] == str(output_dir / "replay_failures.csv")


def test_cli_summary_output_validated(tmp_path: Path):
    price_csv = tmp_path / "price.csv"
    write_price_csv(price_csv, ["2026-05-29"])
    config = write_source_config(tmp_path / "sources.json", price_csv)

    completed, _output_dir = run_replay(tmp_path, "2026-05-29", "2026-05-29", config)

    assert completed.returncode == 0
    assert "Historical Production Replay Summary" in completed.stdout
    assert "Start Date: 2026-05-29" in completed.stdout
    assert "End Date: 2026-05-29" in completed.stdout
    assert "Total Days: 1" in completed.stdout
    assert "Successful Runs: 1" in completed.stdout
    assert "Failed Runs: 0" in completed.stdout
    assert "Provider Failures: 0" in completed.stdout
    assert "Validation Failures: 0" in completed.stdout
    assert "Freshness Failures: 0" in completed.stdout
    assert "Report Failures: 0" in completed.stdout
    assert "Replay Status: PASSED" in completed.stdout
