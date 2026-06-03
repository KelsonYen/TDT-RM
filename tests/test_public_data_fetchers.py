from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from tdt_rm.daily_pipeline import run_daily_pipeline
from tdt_rm.public_data_fetchers import PublicDataFetchContext, PublicDataFetcherRegistry, write_provider_csvs

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "public_data"
AS_OF = date(2026, 6, 2)


def _source(source_id: str, category: str, fixture: str, *, required_fields=()):
    return {
        "source_id": source_id,
        "source_name": source_id,
        "provider_category": category,
        "adapter": "twse_taiex_price" if category == "price" else "generic_json",
        "fixture_path": str(FIXTURE_DIR / fixture),
        "rows_path": "data",
        "freshness_rules": {"max_lag_days": 3},
        "required_fields": list(required_fields),
    }


def _config(*sources):
    return {"sources": list(sources)}


def _fetch_write(tmp_path, config):
    registry = PublicDataFetcherRegistry.from_config(config)
    results = registry.fetch_all(PublicDataFetchContext(as_of=AS_OF, main7_symbols=("2330", "0050")))
    return results, write_provider_csvs(results, tmp_path, AS_OF)


def test_successful_price_fetch_writes_price_csv(tmp_path):
    results, written = _fetch_write(tmp_path, _config(_source("price_fixture", "price", "taiex_price_response.json")))

    assert results[0].success
    price_path = Path(written.provider_csv_paths["price"])
    assert price_path.name == "price.csv"
    assert "taiex_close" in price_path.read_text(encoding="utf-8")
    assert Path(written.fetch_manifest_path).exists()


def test_optional_source_failure_records_warning_and_allow_partial_can_continue(tmp_path):
    config = _config(
        _source("price_fixture", "price", "taiex_price_response.json"),
        _source("bad_fx", "fx", "malformed_response.json", required_fields=("usd_twd_3d_change_pct",)),
    )
    results, written = _fetch_write(tmp_path, config)

    assert "price" in written.provider_csv_paths
    assert "fx" not in written.provider_csv_paths
    assert any(result.source_id == "bad_fx" and not result.success for result in results)
    manifest = json.loads(Path(written.fetch_manifest_path).read_text(encoding="utf-8"))
    assert "bad_fx" in manifest["unavailable_sources"]


def test_price_source_failure_blocks_full_run_without_allow_partial(tmp_path):
    config_path = tmp_path / "sources.json"
    config_path.write_text(json.dumps(_config(_source("bad_price", "price", "malformed_response.json"))), encoding="utf-8")
    summary_path = tmp_path / "summary.json"
    proc = subprocess.run(
        [sys.executable, "scripts/fetch_daily_provider_csvs.py", "--as-of", AS_OF.isoformat(), "--output-dir", str(tmp_path / "inputs"), "--source-config", str(config_path), "--json-summary", str(summary_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "price provider unavailable" in proc.stderr


def test_fetch_manifest_contains_source_success_failure_metadata(tmp_path):
    config = _config(
        _source("price_fixture", "price", "taiex_price_response.json"),
        _source("stale_fx", "fx", "stale_response.json"),
    )
    _, written = _fetch_write(tmp_path, config)

    manifest = json.loads(Path(written.fetch_manifest_path).read_text(encoding="utf-8"))
    assert "attempted_sources" in manifest
    assert "price_fixture" in manifest["successful_sources"]
    assert "stale_fx" in manifest["stale_sources"] or "stale_fx" in manifest["unavailable_sources"]
    assert manifest["provider_csv_paths"]["price"].endswith("price.csv")


def test_generated_provider_csvs_can_be_passed_into_run_daily_pipeline(tmp_path):
    config = _config(
        _source("price_fixture", "price", "taiex_price_response.json"),
        _source("breadth_fixture", "breadth", "market_breadth_response.json", required_fields=("advancing_issues", "declining_issues")),
        _source("foreign_fixture", "foreign_flow", "foreign_flow_response.json", required_fields=("foreign_spot_net_sell_consecutive_days",)),
        _source("fx_fixture", "fx", "fx_response.json", required_fields=("usd_twd_3d_change_pct",)),
        _source("margin_fixture", "margin", "margin_response.json"),
    )
    _, written = _fetch_write(tmp_path / "inputs", config)

    result = run_daily_pipeline(
        as_of=AS_OF,
        output_dir=tmp_path / "outputs",
        price_csv=written.provider_csv_paths["price"],
        foreign_csv=written.provider_csv_paths.get("foreign_flow"),
        fx_csv=written.provider_csv_paths.get("fx"),
        breadth_csv=written.provider_csv_paths.get("breadth"),
        margin_csv=written.provider_csv_paths.get("margin"),
        field_map=written.provider_field_map_path,
    )
    assert result["trade_date"] == AS_OF.isoformat()
    assert Path(result["artifact_paths"]["json"]).exists()


def test_leadership_unavailable_does_not_mark_eti5_available(tmp_path):
    config = _config(_source("price_fixture", "price", "taiex_price_response.json"))
    _, written = _fetch_write(tmp_path / "inputs", config)
    result = run_daily_pipeline(as_of=AS_OF, output_dir=tmp_path / "outputs", price_csv=written.provider_csv_paths["price"], field_map=written.provider_field_map_path)

    assert "ETI-5" not in result["available_eti_components"]


def test_available_eti_components_based_only_on_successfully_sourced_fields(tmp_path):
    config = _config(
        _source("price_fixture", "price", "taiex_price_response.json"),
        _source("fx_fixture", "fx", "fx_response.json", required_fields=("usd_twd_3d_change_pct",)),
        _source("bad_breadth", "breadth", "malformed_response.json", required_fields=("advancing_issues",)),
    )
    _, written = _fetch_write(tmp_path / "inputs", config)
    result = run_daily_pipeline(as_of=AS_OF, output_dir=tmp_path / "outputs", price_csv=written.provider_csv_paths["price"], fx_csv=written.provider_csv_paths.get("fx"), field_map=written.provider_field_map_path)

    assert "ETI-1" in result["available_eti_components"]
    assert "ETI-3" in result["available_eti_components"]
    assert "ETI-4" not in result["available_eti_components"]


def test_no_fake_formal_scores_are_generated(tmp_path):
    config = _config(_source("price_fixture", "price", "taiex_price_response.json"))
    _, written = _fetch_write(tmp_path, config)

    assert "scores" not in written.provider_csv_paths
    assert not (tmp_path / "scores.csv").exists()


def test_cli_can_generate_provider_csvs_from_fixture_responses(tmp_path):
    config_path = tmp_path / "sources.json"
    config_path.write_text(json.dumps(_config(_source("price_fixture", "price", "taiex_price_response.json"))), encoding="utf-8")
    summary_path = tmp_path / "summary.json"
    proc = subprocess.run(
        [sys.executable, "scripts/fetch_daily_provider_csvs.py", "--as-of", AS_OF.isoformat(), "--output-dir", str(tmp_path / "inputs"), "--source-config", str(config_path), "--allow-partial", "--json-summary", str(summary_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "inputs" / "price.csv").exists()
    assert summary_path.exists()


def test_production_required_provider_csvs_are_generated_from_official_parser_fixtures(tmp_path):
    config = _config(
        {**_source("official_price", "price", "official_price_response.json"), "adapter": "twse_fmtqik_price", "min_bars": 60},
        {**_source("official_foreign", "foreign_flow", "foreign_flow_response.json"), "adapter": "twse_t86_foreign_flow"},
        {**_source("official_fx", "fx", "fx_response.json"), "adapter": "taifex_daily_fx"},
        {**_source("official_breadth", "breadth", "market_breadth_response.json"), "adapter": "twse_mi_index_breadth"},
        {**_source("official_futures", "futures", "futures_response.json"), "adapter": "taifex_txf_futures"},
        {**_source("official_options", "options", "options_response.json"), "adapter": "taifex_txo_options"},
        {
            "source_id": "official_leadership",
            "source_name": "official_leadership",
            "provider_category": "leadership",
            "adapter": "leadership_main7",
            "fixture_path": str(FIXTURE_DIR / "leadership_response.json"),
            "rows_path": "data",
            "freshness_rules": {"max_lag_days": 3},
        },
    )

    _, written = _fetch_write(tmp_path / "inputs", config)

    assert set(written.provider_csv_paths) >= {"price", "foreign_flow", "fx", "breadth", "futures", "options", "leadership"}
    assert Path(written.provider_csv_paths["futures"]).name == "futures.csv"
    assert Path(written.provider_csv_paths["options"]).name == "options.csv"
