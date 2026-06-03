from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from tdt_rm.daily_pipeline import run_daily_pipeline
from tdt_rm.public_data_fetchers import PublicDataFetchContext, PublicDataFetcherRegistry, write_provider_csvs

AS_OF = date(2026, 6, 2)
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "public_data"
SAMPLE_FALLBACK = Path("examples/provider_inputs/sample_price_fallback_2026-06-02.csv")


def _live_price(source_id: str = "live_price_failure") -> dict[str, object]:
    return {
        "source_id": source_id,
        "source_name": source_id,
        "provider_category": "price",
        "adapter": "twse_taiex_price",
        "source_type": "twse_json",
        "enabled": True,
        "fallback_order": 10,
        "fixture_path": str(FIXTURE_DIR / "malformed_response.json"),
        "rows_path": "data",
        "freshness_rules": {"max_lag_days": 3},
    }


def _local_csv(path: Path, *, source_id: str = "local_price_csv", order: int = 20, max_lag_days: int = 0) -> dict[str, object]:
    return {
        "source_id": source_id,
        "source_name": source_id,
        "provider_category": "price",
        "adapter": "local_price_fallback",
        "source_type": "local_csv_fallback",
        "enabled": True,
        "fallback_order": order,
        "path": str(path),
        "freshness_rules": {"max_lag_days": max_lag_days},
    }


def _write(tmp_path: Path, config: dict[str, object], *, offline: bool = False):
    registry = PublicDataFetcherRegistry.from_config(config)
    results = registry.fetch_all(PublicDataFetchContext(as_of=AS_OF, offline=offline))
    written = write_provider_csvs(results, tmp_path, AS_OF)
    manifest = json.loads(Path(written.fetch_manifest_path).read_text(encoding="utf-8"))
    return results, written, manifest


def test_live_price_failure_then_local_csv_fallback_succeeds(tmp_path: Path):
    results, written, manifest = _write(tmp_path, {"sources": [_live_price(), _local_csv(SAMPLE_FALLBACK)]})

    assert [result.source_id for result in results] == ["live_price_failure", "local_price_csv"]
    assert results[0].success is False
    assert results[1].success is True
    assert Path(written.provider_csv_paths["price"]).exists()
    assert manifest["data_status"] in {"public_full", "public_partial"}


def test_offline_mode_uses_local_fallback_and_does_not_attempt_live_source(tmp_path: Path):
    results, written, manifest = _write(tmp_path, {"sources": [_live_price(), _local_csv(SAMPLE_FALLBACK)]}, offline=True)

    assert [result.source_id for result in results] == ["local_price_csv"]
    assert "live_price_failure" not in manifest["attempted_sources"]
    assert "price" in written.provider_csv_paths


def test_all_price_sources_fail_blocks_run(tmp_path: Path):
    config_path = tmp_path / "sources.json"
    config_path.write_text(json.dumps({"sources": [_live_price()]}), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "scripts/fetch_daily_provider_csvs.py", "--as-of", AS_OF.isoformat(), "--output-dir", str(tmp_path / "inputs"), "--source-config", str(config_path)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode != 0
    assert "required provider price failed" in proc.stderr


def test_allow_partial_allows_manifest_generation_but_does_not_fabricate_price_csv(tmp_path: Path):
    config_path = tmp_path / "sources.json"
    output_dir = tmp_path / "inputs"
    config_path.write_text(json.dumps({"sources": [_live_price()]}), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "scripts/fetch_daily_provider_csvs.py", "--as-of", AS_OF.isoformat(), "--output-dir", str(output_dir), "--source-config", str(config_path), "--allow-partial"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0
    assert (output_dir / "fetch_manifest.json").exists()
    assert not (output_dir / "price.csv").exists()
    manifest = json.loads((output_dir / "fetch_manifest.json").read_text(encoding="utf-8"))
    assert manifest["data_status"] == "price_unavailable"


def test_fetch_manifest_records_all_attempted_fallback_sources(tmp_path: Path):
    _, _, manifest = _write(tmp_path, {"sources": [_live_price(), _local_csv(SAMPLE_FALLBACK)]})

    attempts = manifest["source_attempts"]
    assert [attempt["source_id"] for attempt in attempts] == ["live_price_failure", "local_price_csv"]
    assert attempts[0]["attempted"] is True
    assert attempts[0]["success"] is False
    assert attempts[0]["failure_reason"]
    assert attempts[1]["local_fallback"] is True
    assert "taiex_close" in attempts[1]["fields_extracted"]


def test_stale_fallback_price_data_fails_freshness_validation(tmp_path: Path):
    stale_csv = tmp_path / "stale_price.csv"
    stale_csv.write_text(
        "date,taiex_close,taiex_ma5,taiex_ma20,taiex_ma60,taiex_ma20_slope\n2026-05-20,42120,42040,41780,40530,36\n",
        encoding="utf-8",
    )
    results, written, manifest = _write(tmp_path / "inputs", {"sources": [_local_csv(stale_csv, max_lag_days=1)]})

    assert results[0].status == "stale"
    assert "price" not in written.provider_csv_paths
    assert not (tmp_path / "inputs" / "price.csv").exists()
    assert manifest["source_attempts"][0]["stale_status"] == "stale"


def test_fallback_generated_price_csv_can_pass_into_run_daily_pipeline(tmp_path: Path):
    _, written, _ = _write(tmp_path / "inputs", {"sources": [_live_price(), _local_csv(SAMPLE_FALLBACK)]})

    result = run_daily_pipeline(as_of=AS_OF, output_dir=tmp_path / "outputs", price_csv=written.provider_csv_paths["price"], field_map=written.provider_field_map_path)

    assert result["trade_date"] == AS_OF.isoformat()
    assert Path(result["artifact_paths"]["json"]).exists()


def test_diagnostics_include_suggested_fallback_command(tmp_path: Path):
    config_path = tmp_path / "sources.json"
    config_path.write_text(json.dumps({"sources": [_live_price()]}), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "scripts/fetch_daily_provider_csvs.py", "--as-of", AS_OF.isoformat(), "--output-dir", str(tmp_path / "inputs"), "--source-config", str(config_path)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert "attempted sources" in proc.stderr
    assert "failure_reason" in proc.stderr
    assert "--price-fallback-csv path/to/price.csv" in proc.stderr


def _live_price_success(source_id: str = "live_price_success") -> dict[str, object]:
    item = _live_price(source_id)
    item["fixture_path"] = str(FIXTURE_DIR / "taiex_price_response.json")
    item["source_type"] = "twse_json"
    return item


def _optional_breadth_success(source_id: str = "breadth_live") -> dict[str, object]:
    return {
        "source_id": source_id,
        "source_name": source_id,
        "provider_category": "breadth",
        "adapter": "generic_json",
        "source_type": "public_json",
        "enabled": True,
        "fallback_order": 10,
        "fixture_path": str(FIXTURE_DIR / "market_breadth_response.json"),
        "rows_path": "data",
        "freshness_rules": {"max_lag_days": 1},
    }


def test_provider_health_all_providers_healthy_and_manifest_summary(tmp_path: Path):
    _, written, manifest = _write(tmp_path, {"sources": [_live_price_success(), _optional_breadth_success()]})

    health = json.loads(Path(written.provider_health_path).read_text(encoding="utf-8"))
    assert (tmp_path / "provider_health.json").exists()
    assert health["providers"]["price_provider"]["status"] == "healthy"
    assert health["providers"]["breadth_provider"]["status"] == "healthy"
    assert manifest["provider_health_summary"]["healthy_providers"] == ["breadth_provider", "price_provider"]
    assert manifest["provider_health"]["price_provider"]["source_type"] == "live"


def test_provider_health_fallback_records_local_fallback_source_type(tmp_path: Path):
    _, written, manifest = _write(tmp_path, {"sources": [_live_price(), _local_csv(SAMPLE_FALLBACK)]})

    health = json.loads(Path(written.provider_health_path).read_text(encoding="utf-8"))
    price = health["providers"]["price_provider"]
    assert price["status"] in {"healthy", "warning"}
    assert price["source_type"] == "local_fallback"
    assert price["diagnostics"]["fallback_attempted"] is True
    assert manifest["provider_health_summary"]["local_fallback_providers"] == ["price_provider"]


def test_provider_health_zero_records_required_failed_optional_warning(tmp_path: Path):
    from tdt_rm.public_data_fetchers import PublicDataFetchResult, build_provider_health

    health = build_provider_health(
        [
            PublicDataFetchResult("price_empty", "price_empty", "price", "success", (), {"date": AS_OF.isoformat()}, {"source_type": "twse_json"}),
            PublicDataFetchResult("breadth_empty", "breadth_empty", "breadth", "success", (), {"date": AS_OF.isoformat()}, {"source_type": "public_json"}),
        ],
        AS_OF,
    )

    assert health["providers"]["price_provider"]["status"] == "failed"
    assert health["providers"]["breadth_provider"]["status"] == "warning"
    assert sorted(health["summary"]["zero_record_providers"]) == ["breadth_provider", "price_provider"]


def test_provider_health_freshness_failure_is_failed_and_fail_closed(tmp_path: Path):
    stale_csv = tmp_path / "stale_price.csv"
    stale_csv.write_text(
        "date,taiex_close,taiex_ma5,taiex_ma20,taiex_ma60,taiex_ma20_slope\n2026-05-20,42120,42040,41780,40530,36\n",
        encoding="utf-8",
    )
    _, written, manifest = _write(tmp_path / "inputs", {"sources": [_local_csv(stale_csv, max_lag_days=1)]})

    health = json.loads(Path(written.provider_health_path).read_text(encoding="utf-8"))
    assert health["providers"]["price_provider"]["status"] == "failed"
    assert health["providers"]["price_provider"]["freshness_status"] == "failed"
    assert manifest["provider_health_summary"]["freshness_failed_providers"] == ["price_provider"]
    assert "price" not in written.provider_csv_paths


def test_provider_health_fetch_exception_preserves_exception_diagnostics(tmp_path: Path):
    broken = _live_price("live_price_exception")
    broken["fixture_path"] = str(tmp_path / "missing_response.json")
    _, written, _ = _write(tmp_path, {"sources": [broken]})

    health = json.loads(Path(written.provider_health_path).read_text(encoding="utf-8"))
    diagnostics = health["providers"]["price_provider"]["diagnostics"]
    assert health["providers"]["price_provider"]["status"] == "failed"
    assert diagnostics["exception_class"]
    assert diagnostics["exception_message"]


def test_provider_health_report_outputs_summary(tmp_path: Path):
    _, written, _ = _write(tmp_path, {"sources": [_live_price(), _local_csv(SAMPLE_FALLBACK)]})

    proc = subprocess.run(
        [sys.executable, "scripts/provider_health_report.py", "--health-json", str(written.provider_health_path)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0
    assert "Provider Health Summary" in proc.stdout
    assert "price_provider: warning" in proc.stdout
    assert "source_type: local_fallback" in proc.stdout


def test_fetch_manifest_requires_provider_health_summary(tmp_path: Path):
    _, _, manifest = _write(tmp_path, {"sources": [_live_price_success()]})

    assert "provider_health_summary" in manifest, "fetch_manifest.json must expose provider health summary"
    assert "provider_health" in manifest, "fetch_manifest.json must expose per-provider health details"


def test_provider_cache_write_and_read_replay_uses_cached_success(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    config = {"sources": [_live_price_success()]}

    results, written, manifest = _write_with_cache(tmp_path / "write", config, cache_dir=cache_dir, cache_mode="write")
    assert results[0].success is True
    assert "price" in written.provider_csv_paths
    assert any(cache_dir.rglob("*.json"))
    assert manifest["source_attempts"][0]["cache"]["hit"] is False

    replay_results, replay_written, replay_manifest = _write_with_cache(tmp_path / "read", config, cache_dir=cache_dir, cache_mode="read", offline=True)

    assert replay_results[0].success is True
    assert replay_results[0].raw_metadata["cache"]["hit"] is True
    assert "price" in replay_written.provider_csv_paths
    assert replay_manifest["source_attempts"][0]["cache"]["hit"] is True


def test_provider_cache_read_miss_does_not_fetch_or_fabricate_price(tmp_path: Path):
    results, written, manifest = _write_with_cache(tmp_path / "read", {"sources": [_live_price_success()]}, cache_dir=tmp_path / "empty_cache", cache_mode="read", offline=True)

    assert results[0].status == "unavailable"
    assert results[0].issues[0].code == "cache_miss"
    assert "price" not in written.provider_csv_paths
    assert manifest["data_status"] == "price_unavailable"


def test_historical_cache_replay_script_writes_replay_summary(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    _write_with_cache(tmp_path / "write", {"sources": [_live_price_success()]}, cache_dir=cache_dir, cache_mode="write")
    config_path = tmp_path / "sources.json"
    config_path.write_text(json.dumps({"sources": [_live_price_success()]}), encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            "scripts/replay_daily_provider_cache.py",
            "--start",
            AS_OF.isoformat(),
            "--end",
            AS_OF.isoformat(),
            "--cache-dir",
            str(cache_dir),
            "--output-dir",
            str(tmp_path / "replay"),
            "--source-config",
            str(config_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0
    summary = json.loads((tmp_path / "replay" / "replay_summary.json").read_text(encoding="utf-8"))
    assert summary["failed_days"] == []
    assert summary["days"][0]["data_status"] in {"public_full", "public_partial"}


def test_daily_report_generator_writes_production_audit_markdown(tmp_path: Path):
    _, written, _ = _write(tmp_path / "inputs", {"sources": [_live_price_success()]})
    report_path = tmp_path / "daily_report.md"

    proc = subprocess.run(
        [
            sys.executable,
            "scripts/generate_daily_report.py",
            "--fetch-manifest",
            str(written.fetch_manifest_path),
            "--output",
            str(report_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0
    text = report_path.read_text(encoding="utf-8")
    assert "TDT-RM Daily Production Audit" in text
    assert "Provider Health" in text
    assert "Source Attempts" in text


def _write_with_cache(tmp_path: Path, config: dict[str, object], *, cache_dir: Path, cache_mode: str, offline: bool = False):
    registry = PublicDataFetcherRegistry.from_config(config)
    results = registry.fetch_all(PublicDataFetchContext(as_of=AS_OF, offline=offline, cache_dir=cache_dir, cache_mode=cache_mode))
    written = write_provider_csvs(results, tmp_path, AS_OF)
    manifest = json.loads(Path(written.fetch_manifest_path).read_text(encoding="utf-8"))
    return results, written, manifest
