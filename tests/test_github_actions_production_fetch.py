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
write_fetch_manifest = _MODULE._write_fetch_manifest

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


def test_production_finmind_live_not_auto_enabled_when_token_present_without_opt_in(monkeypatch):
    monkeypatch.setenv("TDT_RM_PRODUCTION_MODE", "true")
    monkeypatch.setenv("FINMIND_TOKEN", "prod-token")
    monkeypatch.delenv("TDT_RM_ALLOW_FINMIND_LIVE", raising=False)

    assert _MODULE._production_finmind_live_allowed(False) is False


def test_production_finmind_live_enabled_by_explicit_env_opt_in(monkeypatch):
    monkeypatch.setenv("TDT_RM_ALLOW_FINMIND_LIVE", "true")

    assert _MODULE._production_finmind_live_allowed(False) is True


def test_production_finmind_live_not_enabled_without_token_or_opt_in(monkeypatch):
    monkeypatch.setenv("TDT_RM_PRODUCTION_MODE", "true")
    monkeypatch.delenv("FINMIND_TOKEN", raising=False)
    monkeypatch.delenv("FINMIND_API_TOKEN", raising=False)
    monkeypatch.delenv("TDT_RM_ALLOW_FINMIND_LIVE", raising=False)

    assert _MODULE._production_finmind_live_allowed(False) is False

def test_fetch_manifest_written_under_outputs_and_fail_closed_when_dataset_missing(tmp_path: Path):
    staging = tmp_path / "staging"
    production = tmp_path / "inputs" / AS_OF.isoformat()
    reports = tmp_path / "reports" / AS_OF.isoformat()
    artifacts = reports / "artifacts"
    outputs_manifest = tmp_path / "outputs" / AS_OF.isoformat() / "fetch_manifest.json"
    for filename, row in _strict_rows().items():
        if filename != "options.csv":
            _write_csv(staging / filename, row)

    write_fetch_manifest(
        outputs_manifest,
        AS_OF,
        "NOT_READY",
        staging,
        production,
        reports,
        artifacts,
        artifacts / "production_fetch_summary.json",
        artifacts / "provider_health.json",
        artifacts / "validation_report.json",
        allow_finmind_live=False,
        blocking_error="options missing",
    )

    manifest = json.loads(outputs_manifest.read_text(encoding="utf-8"))
    assert manifest["data_status"] == "NOT_READY"
    assert manifest["production_ready"] is False
    assert manifest["fail_closed"] is True
    assert manifest["finmind_live_enabled"] is False
    assert "options" in manifest["missing_production_csvs"]


def test_fetch_manifest_attempt_diagnostics_classifies_http_auth_failure(tmp_path: Path):
    staging = tmp_path / "staging"
    reports = tmp_path / "reports" / AS_OF.isoformat()
    artifacts = reports / "artifacts"
    outputs_manifest = tmp_path / "outputs" / AS_OF.isoformat() / "fetch_manifest.json"
    artifacts.mkdir(parents=True)
    (artifacts / "production_fetch_summary.json").write_text(
        json.dumps(
            {
                "datasets": {
                    "price": {
                        "status": "failed",
                        "failed_providers": [{"provider": "TWSE_OFFICIAL", "message": "HTTP 403 from https://example.invalid after 1 attempts"}],
                    }
                },
                "missing_datasets": ["price.csv"],
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "provider_health.json").write_text(
        json.dumps(
            {
                "providers": {
                    "price_provider": {
                        "dataset": "price",
                        "attempts": [
                            {
                                "provider": "TWSE_OFFICIAL",
                                "status": "failed",
                                "failure_reason": "HTTP 403 from https://example.invalid after 1 attempts",
                                "metadata": {
                                    "endpoint": "https://example.invalid",
                                    "url_fetch": {"status": 403, "attempts": 1, "final_url": "https://example.invalid"},
                                },
                            }
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    write_fetch_manifest(
        outputs_manifest,
        AS_OF,
        "NOT_READY",
        staging,
        tmp_path / "inputs" / AS_OF.isoformat(),
        reports,
        artifacts,
        artifacts / "production_fetch_summary.json",
        artifacts / "provider_health.json",
        artifacts / "validation_report.json",
        allow_finmind_live=False,
        blocking_error="price missing",
    )

    attempt = json.loads(outputs_manifest.read_text(encoding="utf-8"))["source_attempts"][0]
    assert attempt["endpoint_attempted"] == "https://example.invalid"
    assert attempt["http_status"] == 403
    assert attempt["rows_fetched"] == 0
    assert attempt["parser_status"] == "not_reached"
    assert attempt["validation_status"] == "not_reached"
    assert attempt["failure_class"] == "auth/token"


def test_fetch_manifest_finmind_fallback_status_reports_flags_without_secrets(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FINMIND_TOKEN", raising=False)
    monkeypatch.setenv("FINMIND_API_TOKEN", "api-token-secret")
    outputs_manifest = tmp_path / "outputs" / AS_OF.isoformat() / "fetch_manifest.json"

    write_fetch_manifest(
        outputs_manifest,
        AS_OF,
        "NOT_READY",
        tmp_path / "staging",
        tmp_path / "inputs" / AS_OF.isoformat(),
        tmp_path / "reports" / AS_OF.isoformat(),
        tmp_path / "reports" / AS_OF.isoformat() / "artifacts",
        tmp_path / "reports" / AS_OF.isoformat() / "artifacts" / "production_fetch_summary.json",
        tmp_path / "reports" / AS_OF.isoformat() / "artifacts" / "provider_health.json",
        tmp_path / "reports" / AS_OF.isoformat() / "artifacts" / "validation_report.json",
        allow_finmind_live=False,
        blocking_error="not ready",
    )

    manifest_text = outputs_manifest.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert manifest["finmind_fallback"]["allow_finmind"] is False
    assert manifest["finmind_fallback"]["finmind_token_present"] is False
    assert manifest["finmind_fallback"]["finmind_api_token_present"] is True
    assert manifest["finmind_fallback"]["fallback_skipped"] is True
    assert "api-token-secret" not in manifest_text


def test_artifact_contract_fail_closed_requires_diagnostics_but_not_staged_csvs(tmp_path: Path):
    outputs_dir = tmp_path / "outputs" / AS_OF.isoformat()
    reports_dir = tmp_path / "reports" / AS_OF.isoformat()
    artifacts = reports_dir / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "production_fetch_summary.json").write_text(
        json.dumps({"trade_date": AS_OF.isoformat(), "overall_status": "NOT_READY", "datasets": {}, "missing_datasets": ["price.csv"]}),
        encoding="utf-8",
    )
    (artifacts / "provider_health.json").write_text(
        json.dumps({"as_of": AS_OF.isoformat(), "providers": {}, "summary": {"fail_closed": True}}),
        encoding="utf-8",
    )
    write_fetch_manifest(
        outputs_dir / "fetch_manifest.json",
        AS_OF,
        "NOT_READY",
        tmp_path / "staging",
        tmp_path / "inputs" / AS_OF.isoformat(),
        reports_dir,
        artifacts,
        artifacts / "production_fetch_summary.json",
        artifacts / "provider_health.json",
        artifacts / "validation_report.json",
        allow_finmind_live=False,
        blocking_error="provider fetch failed",
    )

    assert _MODULE.validate_fetch_artifact_contract(
        trade_date=AS_OF,
        outputs_dir=outputs_dir,
        reports_dir=reports_dir,
        staging_dir=tmp_path / "staging",
    ) == []


def test_artifact_contract_ready_requires_all_staged_csvs(tmp_path: Path):
    outputs_dir = tmp_path / "outputs" / AS_OF.isoformat()
    reports_dir = tmp_path / "reports" / AS_OF.isoformat()
    artifacts = reports_dir / "artifacts"
    staging = tmp_path / "staging"
    artifacts.mkdir(parents=True)
    for filename, row in _strict_rows().items():
        if filename != "margin.csv":
            _write_csv(staging / filename, row)
    (artifacts / "production_fetch_summary.json").write_text(
        json.dumps({"trade_date": AS_OF.isoformat(), "overall_status": "READY", "datasets": {}, "missing_datasets": []}),
        encoding="utf-8",
    )
    (artifacts / "provider_health.json").write_text(
        json.dumps({"as_of": AS_OF.isoformat(), "providers": {}, "summary": {"fail_closed": False}}),
        encoding="utf-8",
    )
    provider_csv_paths = {dataset: str(staging / f"{dataset}.csv") for dataset in _MODULE.REQUIRED_DATASETS if dataset != "margin"}
    payload = {
        "as_of": AS_OF.isoformat(),
        "trade_date": AS_OF.isoformat(),
        "data_status": "READY",
        "provider_csv_paths": provider_csv_paths,
        "source_attempts": [],
    }
    outputs_dir.mkdir(parents=True)
    (outputs_dir / "fetch_manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    try:
        _MODULE.validate_fetch_artifact_contract(trade_date=AS_OF, outputs_dir=outputs_dir, reports_dir=reports_dir, staging_dir=staging)
    except RuntimeError as exc:
        assert "margin.csv" in str(exc)
    else:
        raise AssertionError("READY artifact contract must require every staged CSV")


def test_attempt_manifest_row_populates_endpoint_status_attempts_and_network_exception(tmp_path: Path):
    row = _MODULE._attempt_manifest_row(
        "price",
        {
            "provider": "TWSE_OFFICIAL",
            "status": "failed",
            "failure_reason": "URL fetch failed from https://example.invalid after 2 attempts: timed out",
            "metadata": {
                "url_fetch": {
                    "initial_url": "https://example.invalid",
                    "final_url": "https://example.invalid/final",
                    "attempts": 2,
                    "network_exception": "timed out",
                    "errors": [{"url": "https://example.invalid/final", "attempt": 2, "network_exception": "timed out", "error": "timed out"}],
                }
            },
        },
        tmp_path,
    )

    assert row["endpoint_attempted"] == "https://example.invalid/final"
    assert row["http_status"] is None
    assert row["attempts"] == 2
    assert row["network_exception"] == "timed out"
    assert row["failure_class"] == "network/proxy"


def test_attempt_manifest_row_classifies_tunnel_403_as_network_layer(tmp_path: Path):
    row = _MODULE._attempt_manifest_row(
        "foreign_flow",
        {
            "provider": "TWSE_OFFICIAL",
            "status": "failed",
            "failure_reason": "URL fetch failed from https://example.invalid after 3 attempts: <urlopen error Tunnel connection failed: 403 Forbidden>",
        },
        tmp_path,
    )

    assert row["failure_class"] == "network/proxy"
    assert row["failure_layer"] == "NETWORK"


def test_attempt_manifest_row_classifies_disabled_finmind_as_config(tmp_path: Path):
    row = _MODULE._attempt_manifest_row(
        "options",
        {
            "provider": "FINMIND_FALLBACK",
            "status": "failed",
            "failure_reason": "live FinMind fallback disabled/unavailable because FINMIND_TOKEN/FINMIND_API_TOKEN is missing and --allow-finmind-live or TDT_RM_ALLOW_FINMIND_LIVE=true opt-in is missing",
        },
        tmp_path,
    )

    assert row["failure_layer"] == "CONFIG"
