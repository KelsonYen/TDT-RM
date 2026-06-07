from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from tdt_rm.bcd_feature_builder import BCDFeatureBuilderContext, enrich_bcd_features, write_bcd_feature_enrichment_trace
from tdt_rm.daily_runner import _bcd_result_from_snapshot
from tdt_rm.daily_snapshot import DailyMarketSnapshot


def _snapshot(**row):
    base = {
        "observed_at": "2026-06-05",
        "close": 100.0,
        "ma5": 99.0,
        "ma20": 95.0,
        "ma60": 90.0,
        "ma20_slope": 1.0,
        "one_day_return_pct": 1.0,
        "two_day_return_pct": 1.5,
        "advancing_issues": 60,
        "declining_issues": 40,
        "foreign_spot_net_sell_consecutive_days": 0,
        "foreign_large_sell": False,
        "futures_hedging_increases": False,
        "usd_twd_3d_change_pct": 0.0,
        "usd_twd_5d_change_pct": 0.0,
        "index_down": False,
        "declining_issues_significantly_gt_advancing": False,
        "breadth_weakens_for_2_days": False,
        "count_main_7_below_ma20": 0,
    }
    base.update(row)
    return DailyMarketSnapshot(
        trade_date=date(2026, 6, 5),
        observed_at=date(2026, 6, 5),
        canonical_row=base,
        field_sources={key: "test_provider" for key in base},
    )


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_generates_breadth_history_from_real_historical_rows(tmp_path: Path):
    input_root = tmp_path / "inputs" / "daily"
    _write_csv(input_root / "2026-06-04" / "breadth.csv", [{"trade_date": "2026-06-04", "advancing_issues": 50, "declining_issues": 50}])
    _write_csv(input_root / "2026-06-05" / "breadth.csv", [{"trade_date": "2026-06-05", "advancing_issues": 60, "declining_issues": 40}])

    result = enrich_bcd_features(
        _snapshot(),
        BCDFeatureBuilderContext(trade_date=date(2026, 6, 5), historical_roots=(input_root,)),
    )

    assert result.snapshot.canonical_row["breadth_history"] == [
        {"trade_date": "2026-06-04", "advancing_issues": 50, "declining_issues": 50, "taiex_return_pct": None},
        {"trade_date": "2026-06-05", "advancing_issues": 60, "declining_issues": 40, "taiex_return_pct": 1.0},
    ]
    assert "breadth_history" in result.trace["generated_fields"]


def test_history_insufficient_does_not_fake_breadth_history_and_bcd_stays_incomplete(tmp_path: Path):
    input_root = tmp_path / "inputs" / "daily"
    _write_csv(input_root / "2026-06-05" / "breadth.csv", [{"trade_date": "2026-06-05", "advancing_issues": 60, "declining_issues": 40}])

    result = enrich_bcd_features(
        _snapshot(),
        BCDFeatureBuilderContext(trade_date=date(2026, 6, 5), historical_roots=(input_root,)),
    )
    bcd = _bcd_result_from_snapshot(result.snapshot, taiex_return_pct=1.0)

    assert "breadth_history" not in result.snapshot.canonical_row
    assert result.trace["missing_reasons"]["breadth_history"].startswith("requires at least")
    assert bcd.data_quality_status == "INCOMPLETE"
    assert "breadth_history" in bcd.missing_components


def test_generates_main7_returns_from_today_and_previous_closes(tmp_path: Path):
    input_root = tmp_path / "inputs" / "daily"
    _write_csv(
        input_root / "2026-06-04" / "leadership.csv",
        [{"trade_date": "2026-06-04", "main_7_symbols": "2330,2454", "2330_close": 100, "2454_close": 200}],
    )
    _write_csv(
        input_root / "2026-06-05" / "leadership.csv",
        [{"trade_date": "2026-06-05", "main_7_symbols": "2330,2454", "2330_close": 110, "2454_close": 190, "2330_turnover_amount": 30, "2454_turnover_amount": 70}],
    )

    result = enrich_bcd_features(
        _snapshot(),
        BCDFeatureBuilderContext(trade_date=date(2026, 6, 5), historical_roots=(input_root,)),
    )

    assert result.snapshot.canonical_row["main7_returns"] == {"2330": 10.0, "2454": -5.0}
    assert result.snapshot.canonical_row["main7_weights"] == {"2330": 0.3, "2454": 0.7}


def test_main7_returns_missing_reason_when_previous_close_absent(tmp_path: Path):
    input_root = tmp_path / "inputs" / "daily"
    _write_csv(input_root / "2026-06-05" / "leadership.csv", [{"trade_date": "2026-06-05", "main_7_symbols": "2330", "2330_close": 110}])

    result = enrich_bcd_features(
        _snapshot(),
        BCDFeatureBuilderContext(trade_date=date(2026, 6, 5), historical_roots=(input_root,)),
    )

    assert "main7_returns" not in result.snapshot.canonical_row
    assert "previous" in result.trace["missing_reasons"]["main7_returns"]


def test_generates_turnover_concentration_from_symbol_level_turnover(tmp_path: Path):
    input_root = tmp_path / "inputs" / "daily"
    _write_csv(
        input_root / "2026-06-05" / "twse_turnover.csv",
        [
            {"trade_date": "2026-06-05", "symbol": "A", "turnover_amount": 50},
            {"trade_date": "2026-06-05", "symbol": "B", "turnover_amount": 30},
            {"trade_date": "2026-06-05", "symbol": "C", "turnover_amount": 20},
        ],
    )

    result = enrich_bcd_features(
        _snapshot(),
        BCDFeatureBuilderContext(trade_date=date(2026, 6, 5), historical_roots=(input_root,)),
    )

    assert result.snapshot.canonical_row["turnover_concentration_topn"] == 1.0
    assert result.snapshot.canonical_row["turnover_concentration"] == 1.0


def test_raw_provider_extras_are_not_overwritten(tmp_path: Path):
    result = enrich_bcd_features(
        _snapshot(breadth_history=[{"trade_date": "raw", "advancing_issues": 1, "declining_issues": 2}]),
        BCDFeatureBuilderContext(trade_date=date(2026, 6, 5), historical_roots=(tmp_path,)),
    )

    assert result.snapshot.canonical_row["breadth_history"] == [{"trade_date": "raw", "advancing_issues": 1, "declining_issues": 2}]
    assert "breadth_history" in result.trace["preserved_provider_fields"]
    assert "breadth_history" not in result.trace["generated_fields"]


def test_enrichment_trace_writes_required_audit_sections(tmp_path: Path):
    result = enrich_bcd_features(
        _snapshot(),
        BCDFeatureBuilderContext(trade_date=date(2026, 6, 5), historical_roots=(tmp_path,)),
    )
    path = write_bcd_feature_enrichment_trace(result.trace, tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["generated_fields"] == []
    assert "unavailable_fields" in payload
    assert "missing_reasons" in payload
    assert "source_paths_used" in payload


def test_bcdinput_receives_more_fields_and_missing_components_decline(tmp_path: Path):
    input_root = tmp_path / "inputs" / "daily"
    _write_csv(input_root / "2026-06-04" / "breadth.csv", [{"trade_date": "2026-06-04", "advancing_issues": 50, "declining_issues": 50}])
    _write_csv(input_root / "2026-06-05" / "breadth.csv", [{"trade_date": "2026-06-05", "advancing_issues": 60, "declining_issues": 40}])
    _write_csv(input_root / "2026-06-04" / "leadership.csv", [{"trade_date": "2026-06-04", "main_7_symbols": "2330", "2330_close": 100}])
    _write_csv(input_root / "2026-06-05" / "leadership.csv", [{"trade_date": "2026-06-05", "main_7_symbols": "2330", "2330_close": 110, "2330_market_cap": 1000}])
    _write_csv(input_root / "2026-06-05" / "turnover.csv", [{"trade_date": "2026-06-05", "symbol": "2330", "turnover_amount": 1000}])
    before = _bcd_result_from_snapshot(_snapshot(), taiex_return_pct=1.0)

    result = enrich_bcd_features(
        _snapshot(),
        BCDFeatureBuilderContext(trade_date=date(2026, 6, 5), historical_roots=(input_root,)),
    )
    after = _bcd_result_from_snapshot(result.snapshot, taiex_return_pct=1.0)

    assert len(after.raw_inputs["breadth_history"]) == 2
    assert after.raw_inputs["main7_returns"] == {"2330": 10.0}
    assert set(after.missing_components) < set(before.missing_components)


def test_main7_returns_from_real_prices(tmp_path: Path):
    input_root = tmp_path / "inputs" / "daily"
    _write_csv(input_root / "2026-06-05" / "leadership.csv", [{"trade_date": "2026-06-05", "main_7_symbols": "2330", "main7_closes": json.dumps({"2330": 121}), "main7_previous_closes": json.dumps({"2330": 110})}])

    result = enrich_bcd_features(_snapshot(), BCDFeatureBuilderContext(trade_date=date(2026, 6, 5), historical_roots=(input_root,)))

    assert result.snapshot.canonical_row["main7_returns"] == {"2330": 10.0}
    assert result.trace["main7_symbols_used"] == ["2330"]
    assert result.trace["source_provider"]["main7_returns"] == "leadership_csv"


def test_main7_weights_from_market_cap(tmp_path: Path):
    input_root = tmp_path / "inputs" / "daily"
    _write_csv(input_root / "2026-06-05" / "leadership.csv", [{"trade_date": "2026-06-05", "main_7_symbols": "2330,2454", "2330_market_cap": 75, "2454_market_cap": 25, "2330_turnover_amount": 1, "2454_turnover_amount": 99}])

    result = enrich_bcd_features(_snapshot(), BCDFeatureBuilderContext(trade_date=date(2026, 6, 5), historical_roots=(input_root,)))

    assert result.snapshot.canonical_row["main7_weights"] == {"2330": 0.75, "2454": 0.25}


def test_main7_weights_from_turnover_value(tmp_path: Path):
    input_root = tmp_path / "inputs" / "daily"
    _write_csv(input_root / "2026-06-05" / "leadership.csv", [{"trade_date": "2026-06-05", "main_7_symbols": "2330,2454", "2330_turnover_amount": 30, "2454_turnover_amount": 70}])

    result = enrich_bcd_features(_snapshot(), BCDFeatureBuilderContext(trade_date=date(2026, 6, 5), historical_roots=(input_root,)))

    assert result.snapshot.canonical_row["main7_weights"] == {"2330": 0.3, "2454": 0.7}


def test_main7_weights_missing_without_fake_equal_weight(tmp_path: Path):
    input_root = tmp_path / "inputs" / "daily"
    _write_csv(input_root / "2026-06-05" / "leadership.csv", [{"trade_date": "2026-06-05", "main_7_symbols": "2330,2454"}])

    result = enrich_bcd_features(_snapshot(), BCDFeatureBuilderContext(trade_date=date(2026, 6, 5), historical_roots=(input_root,)))

    assert "main7_weights" not in result.snapshot.canonical_row
    assert "equal-weight fallback is forbidden" in result.trace["missing_reasons"]["main7_weights"]


def test_main7_concentration_generated_only_when_returns_and_weights_exist(tmp_path: Path):
    input_root = tmp_path / "inputs" / "daily"
    _write_csv(input_root / "2026-06-04" / "leadership.csv", [{"trade_date": "2026-06-04", "main_7_symbols": "2330", "2330_close": 100}])
    _write_csv(input_root / "2026-06-05" / "leadership.csv", [{"trade_date": "2026-06-05", "main_7_symbols": "2330", "2330_close": 110}])
    missing_weight = enrich_bcd_features(_snapshot(), BCDFeatureBuilderContext(trade_date=date(2026, 6, 5), historical_roots=(input_root,)))
    assert "main7_concentration" not in missing_weight.snapshot.canonical_row

    _write_csv(input_root / "2026-06-05" / "leadership.csv", [{"trade_date": "2026-06-05", "main_7_symbols": "2330", "2330_close": 110, "2330_turnover_amount": 10}])
    complete = enrich_bcd_features(_snapshot(), BCDFeatureBuilderContext(trade_date=date(2026, 6, 5), historical_roots=(input_root,)))
    assert complete.snapshot.canonical_row["main7_concentration"] == 10.0
    assert complete.trace["final_fields_passed_to_BCDInput"]["main7_concentration"] == 10.0


def test_turnover_concentration_from_symbol_level_turnover(tmp_path: Path):
    input_root = tmp_path / "inputs" / "daily"
    rows = [{"trade_date": "2026-06-05", "symbol": str(i), "turnover_amount": amount} for i, amount in enumerate([50, 25, 25, 10, 10, 10, 10, 10, 10, 10, 40], start=1)]
    _write_csv(input_root / "2026-06-05" / "symbol_turnover.csv", rows)

    result = enrich_bcd_features(_snapshot(), BCDFeatureBuilderContext(trade_date=date(2026, 6, 5), historical_roots=(input_root,)))

    assert result.snapshot.canonical_row["turnover_concentration_topn"] == 0.95238095
    assert result.snapshot.canonical_row["turnover_concentration"] == 0.95238095
    assert result.trace["turnover_topn_symbols"] == ["1", "11", "2", "3", "4", "5", "6", "7", "8", "9"]


def test_turnover_concentration_not_generated_from_aggregate_market_turnover(tmp_path: Path):
    input_root = tmp_path / "inputs" / "daily"
    _write_csv(input_root / "2026-06-05" / "twse_turnover_or_volume.csv", [{"trade_date": "2026-06-05", "turnover_amount": 1000}])

    result = enrich_bcd_features(_snapshot(), BCDFeatureBuilderContext(trade_date=date(2026, 6, 5), historical_roots=(input_root,)))

    assert "turnover_concentration_topn" not in result.snapshot.canonical_row
    assert "aggregate market turnover cannot produce" in result.trace["missing_reasons"]["turnover_concentration_topn"]


def test_bcd_missing_components_decline_after_main7_and_turnover_recovery(tmp_path: Path):
    input_root = tmp_path / "inputs" / "daily"
    _write_csv(input_root / "2026-06-04" / "leadership.csv", [{"trade_date": "2026-06-04", "main_7_symbols": "2330", "2330_close": 100}])
    _write_csv(input_root / "2026-06-05" / "leadership.csv", [{"trade_date": "2026-06-05", "main_7_symbols": "2330", "2330_close": 110, "2330_turnover_amount": 10}])
    _write_csv(input_root / "2026-06-05" / "symbol_turnover.csv", [{"trade_date": "2026-06-05", "symbol": "2330", "turnover_amount": 10}])
    before = _bcd_result_from_snapshot(_snapshot(), taiex_return_pct=1.0)

    result = enrich_bcd_features(_snapshot(), BCDFeatureBuilderContext(trade_date=date(2026, 6, 5), historical_roots=(input_root,)))
    after = _bcd_result_from_snapshot(result.snapshot, taiex_return_pct=1.0)

    assert {"main7_returns", "main7_weights", "turnover_concentration_topn"}.isdisjoint(after.missing_components)
    assert set(after.missing_components) < set(before.missing_components)
