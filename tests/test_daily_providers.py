import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from tdt_rm.daily_providers import (
    DailyProviderContext,
    DailySnapshotAssembler,
    LocalCsvProvider,
    LocalJsonProvider,
    ManualScoreProvider,
    StaticMappingProvider,
    TAIEXPriceProvider,
)
from tdt_rm.daily_runner import run_daily_production
from tdt_rm.daily_snapshot import load_daily_snapshot_json, validate_daily_snapshot


def complete_row(**overrides):
    row = {
        "observed_at": "2026-05-29",
        "close": 21280.0,
        "ma5": 21300.0,
        "ma20": 21400.0,
        "ma60": 21000.0,
        "ma20_slope": -0.2,
        "one_day_return_pct": -1.0,
        "two_day_return_pct": -1.5,
        "index_5d_return_pct": -2.0,
        "foreign_spot_net_sell_consecutive_days": 4,
        "foreign_large_sell": True,
        "futures_hedging_increases": True,
        "usd_twd_3d_change_pct": 0.7,
        "usd_twd_5d_change_pct": 1.1,
        "index_down": True,
        "advancing_issues": 300,
        "declining_issues": 800,
        "declining_issues_significantly_gt_advancing": True,
        "breadth_weakens_for_2_days": True,
        "count_main_7_below_ma20": 5,
        "tail_risk": 42.5,
        "bcd": 38.0,
        "mhs": 12.0,
    }
    row.update(overrides)
    return row


def write_csv(path: Path, header, row):
    path.write_text(",".join(header) + "\n" + ",".join(str(row.get(key, "")) for key in header) + "\n", encoding="utf-8")


def test_static_mapping_provider_emits_canonical_fields():
    provider = StaticMappingProvider("manual", "Manual row", {"taiex_close": "100", "trade_date": "2026-05-29"})

    result = provider.fetch_or_load(DailyProviderContext(as_of=date(2026, 5, 29)))

    assert result.canonical_fields["close"] == 100.0
    assert result.canonical_fields["observed_at"] == "2026-05-29"
    assert result.field_sources["close"] == "manual"


def test_local_csv_provider_maps_vendor_columns_to_canonical_fields(tmp_path: Path):
    path = tmp_path / "foreign.csv"
    write_csv(path, ["trade_date", "foreign_days", "large_sell"], {"trade_date": "2026-05-29", "foreign_days": "4", "large_sell": "true"})
    provider = LocalCsvProvider(
        "foreign",
        "Foreign CSV",
        path,
        "foreign_flow",
        field_map={"observed_at": "trade_date", "foreign_spot_net_sell_consecutive_days": "foreign_days", "foreign_large_sell": "large_sell"},
    )

    result = provider.fetch_or_load(DailyProviderContext(as_of=date(2026, 5, 29)))

    assert result.canonical_fields["foreign_spot_net_sell_consecutive_days"] == 4
    assert result.canonical_fields["foreign_large_sell"] is True


def test_local_json_provider_maps_source_json_to_canonical_fields(tmp_path: Path):
    path = tmp_path / "fx.json"
    path.write_text(json.dumps({"trade_date": "2026-05-29", "usdtwd_3d_change_pct": "0.72"}), encoding="utf-8")

    result = LocalJsonProvider("fx", "FX JSON", path, "fx").fetch_or_load(DailyProviderContext(as_of=date(2026, 5, 29)))

    assert result.canonical_fields["usd_twd_3d_change_pct"] == 0.72


def test_daily_snapshot_assembler_merges_outputs_and_populates_sources():
    context = DailyProviderContext(as_of=date(2026, 5, 29))
    providers = [
        StaticMappingProvider("price", "Price", complete_row(tail_risk="", bcd="", mhs=""), category="price", source_kind="price"),
        StaticMappingProvider("scores", "Scores", {"observed_at": "2026-05-29", "tail_risk": 40.0, "bcd": 35.0}, category="scores", source_kind="formal"),
    ]

    result = DailySnapshotAssembler(providers).assemble(context)

    assert result.validation.is_valid
    assert result.snapshot.canonical_row["tail_risk"] == 40.0
    assert "bcd" not in result.snapshot.canonical_row
    assert "bcd" not in result.snapshot.field_sources
    assert result.snapshot.field_sources["tail_risk"] == "scores"
    assert "scores" in result.snapshot.source_metadata


def test_provider_field_map_cannot_supply_bcd():
    provider = StaticMappingProvider(
        "options_csv",
        "Options CSV",
        {"trade_date": "2026-05-29", "bcd_score": 35.0, "tail_risk": 40.0},
        category="options",
    )

    result = provider.fetch_or_load(
        DailyProviderContext(
            as_of=date(2026, 5, 29),
            provider_field_maps={"options_csv": {"bcd": "bcd_score"}},
        )
    )

    assert "bcd" not in result.canonical_fields
    assert result.canonical_fields["tail_risk"] == 40.0


def test_field_conflicts_are_detected_and_reported():
    providers = [
        StaticMappingProvider("auto", "Auto", complete_row(close=100.0), category="price", source_kind="auto"),
        StaticMappingProvider("manual", "Manual", {"observed_at": "2026-05-29", "close": 101.0}, category="manual", source_kind="manual"),
    ]

    result = DailySnapshotAssembler(providers).assemble(DailyProviderContext(as_of=date(2026, 5, 29)))

    assert result.snapshot.canonical_row["close"] == 101.0
    assert result.conflicts
    assert any("field conflict for close" in warning for warning in result.warnings)


def test_manual_formal_scores_override_proxy_fields():
    providers = [
        StaticMappingProvider("proxy", "Proxy", complete_row(tail_risk=10.0, bcd=11.0), category="scores", source_kind="proxy"),
        ManualScoreProvider("manual_scores", "Manual scores", {"trade_date": "2026-05-29", "tail_risk": 42.5, "bcd": 38.0, "mhs": 12.0}),
    ]

    result = DailySnapshotAssembler(providers).assemble(DailyProviderContext(as_of=date(2026, 5, 29)))

    assert result.snapshot.canonical_row["tail_risk"] == 42.5
    assert "bcd" not in result.snapshot.canonical_row
    assert result.snapshot.field_sources["tail_risk"] == "manual_scores"


def test_missing_optional_provider_categories_do_not_fail_snapshot():
    row = {key: complete_row()[key] for key in ("observed_at", "close", "ma5", "ma20", "ma60", "ma20_slope")}
    result = DailySnapshotAssembler([StaticMappingProvider("price", "Price", row, category="price", source_kind="price")]).assemble(
        DailyProviderContext(as_of=date(2026, 5, 29))
    )

    assert result.validation.is_valid
    assert "fx" in result.missing_field_categories or "margin" in result.missing_field_categories


def test_missing_required_price_fields_fail_validation():
    row = complete_row()
    row.pop("close")
    result = DailySnapshotAssembler([StaticMappingProvider("manual", "Manual", row)]).assemble(DailyProviderContext(as_of=date(2026, 5, 29)))

    assert not result.validation.is_valid
    assert any(issue.code == "missing_required_field" for issue in result.validation.issues)


def test_assembled_snapshot_can_run_daily_production(tmp_path: Path):
    assembled = DailySnapshotAssembler([StaticMappingProvider("manual", "Manual", complete_row())]).assemble(
        DailyProviderContext(as_of=date(2026, 5, 29))
    )

    production = run_daily_production(
        as_of=date(2026, 5, 29),
        output_dir=tmp_path,
        snapshot=assembled.snapshot,
        timestamp=datetime(2026, 5, 29, 9, 0, tzinfo=UTC),
    )

    assert production.json_path.exists()
    assert production.payload["trade_date"] == "2026-05-29"


def test_taiex_price_provider_reuses_price_feature_derivation(tmp_path: Path):
    path = tmp_path / "price.csv"
    from datetime import timedelta

    rows = ["date,close,turnover_amount"]
    start = date(2026, 3, 1)
    for index in range(61):
        rows.append(f"{(start + timedelta(days=index)).isoformat()},{100 + index},1000000")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    result = TAIEXPriceProvider(source_path=path).fetch_or_load(DailyProviderContext(as_of=date(2026, 4, 30)))

    assert result.canonical_fields["close"] == 160.0
    assert result.canonical_fields["ma20"] > 0
    assert len(result.price_bars) == 61


def test_assemble_daily_snapshot_cli_writes_valid_snapshot_json(tmp_path: Path):
    output = tmp_path / "assembled.json"
    cmd = [
        sys.executable,
        "scripts/assemble_daily_snapshot.py",
        "--as-of",
        "2026-05-29",
        "--price-csv",
        "examples/provider_inputs/sample_price.csv",
        "--foreign-csv",
        "examples/provider_inputs/sample_foreign_flow.csv",
        "--fx-csv",
        "examples/provider_inputs/sample_fx.csv",
        "--breadth-csv",
        "examples/provider_inputs/sample_breadth.csv",
        "--margin-csv",
        "examples/provider_inputs/sample_margin.csv",
        "--scores-csv",
        "examples/provider_inputs/sample_scores.csv",
        "--field-map",
        "examples/provider_inputs/sample_provider_field_map.json",
        "--output-json",
        str(output),
        "--validate",
        "--allow-warnings",
    ]

    completed = subprocess.run(cmd, check=True, text=True, capture_output=True)

    assert "trade_date: 2026-05-29" in completed.stdout
    snapshot = load_daily_snapshot_json(output)
    assert validate_daily_snapshot(snapshot, as_of=date(2026, 5, 29)).is_valid


def test_sample_provider_fixture_assembles_without_optional_margin(tmp_path: Path):
    output = tmp_path / "assembled_no_margin.json"
    cmd = [
        sys.executable,
        "scripts/assemble_daily_snapshot.py",
        "--as-of",
        "2026-05-29",
        "--price-csv",
        "examples/provider_inputs/sample_price.csv",
        "--foreign-csv",
        "examples/provider_inputs/sample_foreign_flow.csv",
        "--fx-csv",
        "examples/provider_inputs/sample_fx.csv",
        "--breadth-csv",
        "examples/provider_inputs/sample_breadth.csv",
        "--leadership-csv",
        "examples/provider_inputs/sample_leadership.csv",
        "--scores-csv",
        "examples/provider_inputs/sample_scores.csv",
        "--field-map",
        "examples/provider_inputs/sample_provider_field_map.json",
        "--output-json",
        str(output),
        "--validate",
        "--allow-warnings",
    ]

    completed = subprocess.run(cmd, check=True, text=True, capture_output=True)

    assert "missing_field_categories: margin" in completed.stdout
    snapshot = load_daily_snapshot_json(output)
    validation = validate_daily_snapshot(snapshot, as_of=date(2026, 5, 29))
    assert validation.is_valid
    assert snapshot.canonical_row["tail_risk"] == 32.0
    assert snapshot.field_sources["tail_risk"] == "scores_csv"
    assert set(validation.coverage.available_eti_components) == {"ETI-1", "ETI-2", "ETI-3", "ETI-4", "ETI-5"}


def test_assemble_daily_snapshot_cli_requires_price_provider(tmp_path: Path):
    output = tmp_path / "no_price.json"
    cmd = [
        sys.executable,
        "scripts/assemble_daily_snapshot.py",
        "--as-of",
        "2026-05-29",
        "--fx-csv",
        "examples/provider_inputs/sample_fx.csv",
        "--output-json",
        str(output),
    ]

    completed = subprocess.run(cmd, text=True, capture_output=True)

    assert completed.returncode != 0
    assert "--price-csv is required" in completed.stderr


def test_eti_availability_ignores_unsourced_canonical_fields():
    row = complete_row()
    field_sources = {key: "price" for key in ("observed_at", "close", "ma20", "ma5", "ma60", "ma20_slope")}
    result = DailySnapshotAssembler([StaticMappingProvider("price", "Price", row, category="price", source_kind="price")]).assemble(
        DailyProviderContext(as_of=date(2026, 5, 29))
    )
    snapshot = result.snapshot
    snapshot = type(snapshot)(
        trade_date=snapshot.trade_date,
        observed_at=snapshot.observed_at,
        canonical_row=snapshot.canonical_row,
        price_bars=snapshot.price_bars,
        field_sources=field_sources,
        source_metadata=snapshot.source_metadata,
        data_status=snapshot.data_status,
        limitations=snapshot.limitations,
        warnings=snapshot.warnings,
    )

    validation = validate_daily_snapshot(snapshot, as_of=date(2026, 5, 29))

    assert set(validation.coverage.available_eti_components) == {"ETI-1"}
