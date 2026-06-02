import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from tdt_rm.daily_runner import build_daily_payload, render_daily_markdown
from tdt_rm.daily_validation import (
    build_daily_run_manifest,
    validate_daily_artifacts,
    validate_daily_payload,
)
from tdt_rm.market_data import MarketPriceBar


def sample_bars(count=70):
    start = date(2026, 1, 1)
    return [
        MarketPriceBar(
            observed_at=date.fromordinal(start.toordinal() + index),
            close=10000 + index * 10,
            turnover_amount=1_000_000 + index,
        )
        for index in range(count)
    ]


def sample_payload():
    return build_daily_payload(sample_bars(), timestamp=datetime(2026, 3, 11, 8, 30, tzinfo=UTC))


def write_artifacts(tmp_path: Path, payload=None):
    payload = payload or sample_payload()
    json_path = tmp_path / f"tdt_rm_daily_{payload['trade_date']}.json"
    markdown_path = tmp_path / f"tdt_rm_daily_{payload['trade_date']}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_daily_markdown(payload), encoding="utf-8")
    return json_path, markdown_path, payload


def test_valid_payload_passes_with_price_only_warning():
    result = validate_daily_payload(sample_payload())

    assert result.passed
    assert result.status == "warning"
    assert not result.errors
    assert any(issue.code == "price_only_provisional" for issue in result.warnings)


def test_missing_required_field_fails():
    payload = sample_payload()
    payload.pop("signal")

    result = validate_daily_payload(payload)

    assert result.has_errors
    assert any(issue.code == "missing_required_field" and issue.field == "signal" for issue in result.errors)


def test_stale_trade_date_produces_warning_or_error():
    payload = sample_payload()

    warning_result = validate_daily_payload(payload, as_of=date(2026, 3, 12))
    error_result = validate_daily_payload(payload, as_of=date(2026, 3, 16))

    assert any(issue.code == "stale_trade_date" for issue in warning_result.warnings)
    assert warning_result.passed
    assert any(issue.code == "stale_trade_date" for issue in error_result.errors)
    assert error_result.has_errors


def test_price_only_provisional_emits_warning_but_does_not_fail_by_itself():
    payload = sample_payload()

    result = validate_daily_payload(payload)

    assert result.passed
    assert not result.errors
    assert [issue.code for issue in result.warnings] == ["price_only_provisional"]


def test_missing_markdown_artifact_fails(tmp_path: Path):
    json_path, markdown_path, _ = write_artifacts(tmp_path)
    markdown_path.unlink()

    result = validate_daily_artifacts(json_path, markdown_path)

    assert result.has_errors
    assert any(issue.code == "missing_markdown_artifact" for issue in result.errors)


def test_markdown_trade_date_and_signal_mismatch_fails(tmp_path: Path):
    json_path, markdown_path, _ = write_artifacts(tmp_path)
    markdown_path.write_text("# wrong report\n- Signal: Blue\n- Date: 2026-01-01\n", encoding="utf-8")

    result = validate_daily_artifacts(json_path, markdown_path)

    assert any(issue.code == "markdown_trade_date_mismatch" for issue in result.errors)
    assert any(issue.code == "markdown_signal_mismatch" for issue in result.errors)


def test_manifest_includes_artifact_paths_and_validation_result(tmp_path: Path):
    json_path, markdown_path, payload = write_artifacts(tmp_path)
    validation = validate_daily_artifacts(json_path, markdown_path)

    manifest = build_daily_run_manifest(
        payload,
        json_path,
        markdown_path,
        command="pytest",
        git_sha="abc123",
        validation=validation,
    )

    assert manifest["artifact_paths"] == {"json": str(json_path), "markdown": str(markdown_path)}
    assert manifest["validation_status"] == validation.status
    assert manifest["validation"]["warning_count"] == 1
    assert manifest["command"] == "pytest"
    assert manifest["git_sha"] == "abc123"


def test_validate_daily_artifacts_applies_as_of_staleness(tmp_path: Path):
    json_path, markdown_path, _ = write_artifacts(tmp_path)

    result = validate_daily_artifacts(json_path, markdown_path, as_of=date(2026, 3, 16))

    assert result.has_errors
    assert any(issue.code == "stale_trade_date" for issue in result.errors)


def test_cli_as_of_staleness_does_not_duplicate_payload_warnings(tmp_path: Path):
    json_path, markdown_path, _ = write_artifacts(tmp_path)

    valid = subprocess.run(
        [
            sys.executable,
            "scripts/validate_daily_production.py",
            "--json-path",
            str(json_path),
            "--markdown-path",
            str(markdown_path),
            "--as-of",
            "2026-03-12",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert valid.returncode == 0, valid.stdout + valid.stderr
    validation = json.loads(valid.stdout)
    warning_codes = [warning["code"] for warning in validation["warnings"]]
    assert warning_codes.count("price_only_provisional") == 1
    assert warning_codes.count("stale_trade_date") == 1


def test_cli_exits_zero_for_valid_artifacts_and_nonzero_for_invalid_artifacts(tmp_path: Path):
    json_path, markdown_path, _ = write_artifacts(tmp_path)
    manifest_path = tmp_path / "manifest.json"

    valid = subprocess.run(
        [
            sys.executable,
            "scripts/validate_daily_production.py",
            "--json-path",
            str(json_path),
            "--markdown-path",
            str(markdown_path),
            "--manifest-out",
            str(manifest_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert valid.returncode == 0, valid.stdout + valid.stderr
    assert manifest_path.exists()

    invalid = subprocess.run(
        [
            sys.executable,
            "scripts/validate_daily_production.py",
            "--json-path",
            str(json_path),
            "--markdown-path",
            str(tmp_path / "missing.md"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert invalid.returncode != 0
