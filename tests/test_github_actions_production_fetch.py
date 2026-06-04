from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import importlib.util
import sys

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_github_actions_production_fetch.py"
_SPEC = importlib.util.spec_from_file_location("run_github_actions_production_fetch", _SCRIPT_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
REQUIRED_PRODUCTION_FILES = _MODULE.REQUIRED_PRODUCTION_FILES
build_production_input_directory = _MODULE.build_production_input_directory
validate_required_production_files = _MODULE.validate_required_production_files

AS_OF = date(2026, 6, 3)


def _write_csv(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


def _strict_rows() -> dict[str, dict[str, object]]:
    base = {"trade_date": AS_OF.isoformat(), "provider_source": "TWSE_OFFICIAL:fixture", "source_type": "REAL_PROVIDER"}
    return {
        "price.csv": {**base, "close": 42000, "ma5": 41900, "ma20": 41500, "ma60": 40000, "ma20_slope": 1, "one_day_return_pct": 0.1, "two_day_return_pct": 0.2, "close_below_ma20_consecutive_days": 0, "index_5d_return_pct": 1.2, "return_60d_pct": 3.4, "previous_ma60": 39900, "turnover_amount": 1000000000},
        "foreign_flow.csv": {**base, "foreign_spot_net_buy": 100, "foreign_spot_net_sell": 0, "foreign_spot_net_sell_consecutive_days": 0, "foreign_spot_large_sell": False, "foreign_large_sell": False},
        "fx.csv": {**base, "usd_twd_3d_change_pct": 0.1, "usd_twd_5d_change_pct": 0.2, "twd_appreciates": False, "twd_stable": True, "twd_depreciates_significantly": False},
        "breadth.csv": {**base, "index_down": False, "advancing_issues": 500, "declining_issues": 400, "declining_issues_significantly_expand": False, "declining_issues_significantly_gt_advancing": False, "declining_gt_advancing_consecutive_days": 0, "breadth_weakens_for_2_days": False},
        "futures.csv": {**base, "futures_hedging_increases": False, "futures_hedging_significant": False, "futures_net_short_increases": False, "futures_net_short_decreases": True},
        "options.csv": {**base, "pcr_stable": True, "pcr_rises": False, "vix_stable": True, "vix_rises": False, "tail_risk": 20, "bcd": 30},
        "leadership.csv": {**base, "count_main_7_below_ma20": 1, "count_main_7_below_ma60": 0, "majority_main_7_assets_above_ma20": True, "main_7_symbols": "2330,0050", "main_7_below_ma20_symbols": "0050", "mhs": 85},
        "margin.csv": {**base, "margin_balance_5d_flat_or_down": True, "hot_stock_margin_fast_increase": False, "margin_balance_5d_increases": False, "index_5d_return_pct": 1.2, "margin_balance_5d_decline_pct": 0.2, "margin_not_retreating": False},
    }


def test_manifest_creation_and_required_file_validation(tmp_path: Path):
    staging = tmp_path / "staging"
    production = tmp_path / "inputs" / AS_OF.isoformat()
    for filename, row in _strict_rows().items():
        _write_csv(staging / filename, row)

    build_production_input_directory(trade_date=AS_OF, staging_dir=staging, production_dir=production)

    assert sorted(path.name for path in production.iterdir()) == sorted(REQUIRED_PRODUCTION_FILES)
    manifest = json.loads((production / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["trade_date"] == AS_OF.isoformat()
    assert set(manifest["required_files"]) == set(REQUIRED_PRODUCTION_FILES)
    assert validate_required_production_files(trade_date=AS_OF, input_dir=production) == []


def test_fail_closed_when_required_provider_file_is_missing(tmp_path: Path):
    staging = tmp_path / "staging"
    production = tmp_path / "inputs" / AS_OF.isoformat()
    for filename, row in _strict_rows().items():
        if filename != "margin.csv":
            _write_csv(staging / filename, row)

    build_production_input_directory(trade_date=AS_OF, staging_dir=staging, production_dir=production)
    errors = validate_required_production_files(trade_date=AS_OF, input_dir=production)

    assert any("twse_margin.csv" in error for error in errors)


def test_fail_closed_on_trade_date_mismatch(tmp_path: Path):
    staging = tmp_path / "staging"
    production = tmp_path / "inputs" / AS_OF.isoformat()
    rows = _strict_rows()
    rows["margin.csv"] = {**rows["margin.csv"], "trade_date": "2026-06-02"}
    for filename, row in rows.items():
        _write_csv(staging / filename, row)

    build_production_input_directory(trade_date=AS_OF, staging_dir=staging, production_dir=production)
    errors = validate_required_production_files(trade_date=AS_OF, input_dir=production)

    assert any("twse_margin.csv" in error and "trade_date mismatch" in error for error in errors)


def test_no_demo_mock_or_synthetic_fallback_in_production_mode(tmp_path: Path):
    staging = tmp_path / "staging"
    production = tmp_path / "inputs" / AS_OF.isoformat()
    rows = _strict_rows()
    rows["price.csv"] = {**rows["price.csv"], "source_type": "synthetic"}
    for filename, row in rows.items():
        _write_csv(staging / filename, row)

    build_production_input_directory(trade_date=AS_OF, staging_dir=staging, production_dir=production)
    errors = validate_required_production_files(trade_date=AS_OF, input_dir=production)

    assert any("forbidden source_type 'synthetic'" in error for error in errors)


def test_production_finmind_live_auto_enabled_when_token_present(monkeypatch):
    monkeypatch.setenv("TDT_RM_PRODUCTION_MODE", "true")
    monkeypatch.setenv("FINMIND_TOKEN", "prod-token")
    monkeypatch.delenv("TDT_RM_ALLOW_FINMIND_LIVE", raising=False)

    assert _MODULE._production_finmind_live_allowed(False) is True


def test_production_finmind_live_not_enabled_without_token_or_opt_in(monkeypatch):
    monkeypatch.setenv("TDT_RM_PRODUCTION_MODE", "true")
    monkeypatch.delenv("FINMIND_TOKEN", raising=False)
    monkeypatch.delenv("FINMIND_API_TOKEN", raising=False)
    monkeypatch.delenv("TDT_RM_ALLOW_FINMIND_LIVE", raising=False)

    assert _MODULE._production_finmind_live_allowed(False) is False
