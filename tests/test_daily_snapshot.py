import json
from datetime import UTC, date, datetime
from pathlib import Path

from tdt_rm import MarketPriceBar
from tdt_rm.daily_runner import build_daily_payload_from_snapshot, run_daily_production
from tdt_rm.daily_snapshot import (
    DailyMarketSnapshot,
    build_source_coverage,
    derive_eti_available_components,
    load_daily_snapshot_csv,
    load_daily_snapshot_json,
    validate_daily_snapshot,
)


def canonical_row(**overrides):
    row = {
        "observed_at": "2026-03-31",
        "close": 100.0,
        "ma5": 101.0,
        "ma20": 102.0,
        "ma60": 99.0,
        "ma20_slope": -0.2,
        "one_day_return_pct": -1.0,
        "two_day_return_pct": -2.0,
        "index_5d_return_pct": -3.0,
        "close_below_ma20_consecutive_days": 2,
        "index_down": True,
        "foreign_spot_net_sell_consecutive_days": 2,
        "usd_twd_3d_change_pct": 0.6,
        "declining_issues_significantly_gt_advancing": True,
        "count_main_7_below_ma20": 4,
    }
    row.update(overrides)
    return row


def price_bars(count=70):
    start = date(2026, 1, 21)
    return [
        MarketPriceBar(
            observed_at=date.fromordinal(start.toordinal() + index),
            close=100 + index * 0.2,
            turnover_amount=1_000_000 + index,
        )
        for index in range(count - 1)
    ] + [MarketPriceBar(observed_at=date(2026, 3, 31), close=100.0, turnover_amount=1_000_000)]


def snapshot(**row_overrides):
    return DailyMarketSnapshot(
        trade_date=date(2026, 3, 31),
        observed_at=date(2026, 3, 31),
        canonical_row=canonical_row(**row_overrides),
        price_bars=tuple(price_bars()),
        field_sources={key: "local" for key in canonical_row(**row_overrides)},
        source_metadata={"local": {"name": "Local fixture", "retrieved_at": "2026-03-31T09:00:00Z"}},
        data_status="enriched_snapshot",
    )


def test_loading_snapshot_json(tmp_path: Path):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot(tail_risk=12.5, bcd=7.5).as_dict()), encoding="utf-8")

    loaded = load_daily_snapshot_json(path)

    assert loaded.trade_date == date(2026, 3, 31)
    assert loaded.canonical_row["tail_risk"] == 12.5
    assert loaded.price_bars[-1].observed_at == date(2026, 3, 31)


def test_loading_one_row_snapshot_csv(tmp_path: Path):
    path = tmp_path / "snapshot.csv"
    path.write_text("trade_date,close,ma5,ma20,ma60,ma20_slope\n2026-03-31,100,101,102,99,-0.2\n", encoding="utf-8")

    loaded = load_daily_snapshot_csv(path)

    assert loaded.trade_date == date(2026, 3, 31)
    assert loaded.canonical_row["close"] == "100"
    assert loaded.field_sources["close"] == "input_csv"


def test_field_map_handling(tmp_path: Path):
    path = tmp_path / "snapshot.csv"
    path.write_text("day,last,five,twenty,sixty,slope\n2026-03-31,100,101,102,99,-0.2\n", encoding="utf-8")

    loaded = load_daily_snapshot_csv(
        path,
        field_map={"observed_at": "day", "close": "last", "ma5": "five", "ma20": "twenty", "ma60": "sixty", "ma20_slope": "slope"},
    )

    assert loaded.canonical_row["close"] == "100"
    assert loaded.canonical_row["ma20"] == "102"


def test_source_coverage_generation():
    coverage = build_source_coverage(snapshot())

    assert coverage.data_status == "enriched_snapshot"
    assert coverage.field_sources["close"].source_name == "Local fixture"
    assert set(coverage.available_eti_components) == {"ETI-1", "ETI-2", "ETI-3", "ETI-4", "ETI-5"}


def test_eti_available_components_derivation_marks_missing_optional_unavailable():
    snap = snapshot(
        foreign_spot_net_sell_consecutive_days="",
        usd_twd_3d_change_pct="",
        declining_issues_significantly_gt_advancing="",
        count_main_7_below_ma20="",
    )

    assert derive_eti_available_components(snap) == {"ETI-1", "ETI-4"}  # index_down remains supplied
    validation = validate_daily_snapshot(snap)
    assert validation.is_valid


def test_missing_required_price_fields_fails():
    snap = snapshot(close="")

    validation = validate_daily_snapshot(snap)

    assert not validation.is_valid
    assert any(issue.code == "missing_required_field" and issue.field == "canonical_row.close" for issue in validation.issues)


def test_snapshot_validation_rejects_provider_supplied_bcd():
    snap = snapshot(bcd=35.0)

    validation = validate_daily_snapshot(snap)

    assert not validation.is_valid
    assert any(issue.code == "provider_supplied_bcd" for issue in validation.issues)


def test_snapshot_validation_rejects_options_csv_bcd_source():
    snap = snapshot()
    snap = DailyMarketSnapshot(
        trade_date=snap.trade_date,
        observed_at=snap.observed_at,
        canonical_row={key: value for key, value in snap.canonical_row.items() if key != "bcd"},
        price_bars=snap.price_bars,
        field_sources={**snap.field_sources, "bcd": "options_csv"},
        source_metadata=snap.source_metadata,
        data_status=snap.data_status,
        limitations=snap.limitations,
        warnings=snap.warnings,
    )

    validation = validate_daily_snapshot(snap)

    assert not validation.is_valid
    assert any(issue.code == "forbidden_bcd_source" for issue in validation.issues)


def test_formal_tail_risk_is_used_but_bcd_is_computed_only():
    payload = build_daily_payload_from_snapshot(
        snapshot(tail_risk=12.25),
        timestamp=datetime(2026, 3, 31, 9, 0, tzinfo=UTC),
    )

    assert payload["tail_risk"] == 12.25
    assert payload["bcd"] is None
    assert payload["bcd_status"] == "INCOMPLETE"
    assert payload["data"]["fallback_proxies"]["bcd"]["status"] == "incomplete_bcd"


def test_price_only_proxy_fallback_is_recorded_when_tail_risk_bcd_absent():
    payload = build_daily_payload_from_snapshot(snapshot())

    assert set(payload["data"]["fallback_proxies"]) == {"tail_risk", "bcd"}
    assert payload["data"]["fallback_proxies"]["tail_risk"]["status"] == "price_only_proxy"


def test_build_daily_payload_from_snapshot_preserves_existing_payload_shape():
    payload = build_daily_payload_from_snapshot(snapshot())

    assert {"timestamp", "model_version", "trade_date", "market_regime", "tcwrs", "mhs", "eti_5", "tail_risk", "bcd", "cp", "cp_level", "signal", "equity_exposure_limit", "inputs", "scores", "traces", "data", "etf_exit"} <= set(payload)
    assert payload["data"]["available_eti_components"]
    assert payload["etf_exit"]["status"] == "not_integrated"


def test_run_daily_production_snapshot_path_writes_artifacts(tmp_path: Path):
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot(tail_risk=10.0).as_dict()), encoding="utf-8")
    out = tmp_path / "out"

    result = run_daily_production(
        as_of=date(2026, 3, 31),
        output_dir=out,
        snapshot_path=snapshot_path,
        timestamp=datetime(2026, 3, 31, 9, 0, tzinfo=UTC),
        write_manifest=True,
        git_sha="abc123",
    )

    assert result.json_path.exists()
    assert result.markdown_path.exists()
    assert result.manifest_path and result.manifest_path.exists()
    assert "台股雙溫度計風控報告" in result.markdown_path.read_text(encoding="utf-8")


def test_default_run_daily_production_behavior_remains_backward_compatible(tmp_path: Path):
    class Fetcher:
        def fetch_bars(self, *, as_of, min_bars):
            assert min_bars == 61
            return price_bars()

    result = run_daily_production(
        as_of=date(2026, 3, 31),
        output_dir=tmp_path,
        fetcher=Fetcher(),
        timestamp=datetime(2026, 3, 31, 9, 0, tzinfo=UTC),
    )

    assert result.payload["data"]["status"] == "price_only_provisional"
    assert result.json_path.exists()
