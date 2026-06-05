from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
import importlib.util

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "fetch_daily_data_multi_provider.py"
_SPEC = importlib.util.spec_from_file_location("fetch_daily_data_multi_provider", _SCRIPT_PATH)
assert _SPEC and _SPEC.loader
_FETCH_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FETCH_MODULE)
_fetch_dataset = _FETCH_MODULE._fetch_dataset
_provider_chains = _FETCH_MODULE._provider_chains
from tdt_rm.data_providers import ProviderContext, ProviderResult
from tdt_rm.data_providers.finmind import FinMindProvider
from tdt_rm.data_providers.normalizers import REAL_SOURCE_TYPE, reconciliation_checks, validate_strict_row


class StaticProvider:
    def __init__(self, name: str, row: dict[str, object] | None = None, error: Exception | None = None):
        self.name = name
        self.row = row or {}
        self.error = error
        self.datasets = ("price",)

    def fetch(self, dataset: str, context: ProviderContext) -> ProviderResult:
        if self.error is not None:
            raise self.error
        return ProviderResult(dataset, self.name, self.name, self.row, {"fixture_provider": self.name})


def _price_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "trade_date": "2026-06-03",
        "provider_source": "unit",
        "source_type": REAL_SOURCE_TYPE,
        "close": 42000.0,
        "ma5": 41900.0,
        "ma20": 41500.0,
        "ma60": 40000.0,
        "ma20_slope": 12.0,
        "one_day_return_pct": 0.1,
        "two_day_return_pct": 0.2,
        "close_below_ma20_consecutive_days": 0,
        "index_5d_return_pct": 1.2,
        "return_60d_pct": 3.4,
        "previous_ma60": 39900.0,
        "turnover_amount": 1000000000,
    }
    row.update(overrides)
    return row


def test_provider_chain_is_official_source_first_and_finmind_last():
    chains = _provider_chains(None)
    price_chain_names = [provider.name for provider in chains["price"]]
    fx_chain_names = [provider.name for provider in chains["fx"]]

    assert price_chain_names == ["TWSE_OFFICIAL", "TAIWAN_INDEX_PLUS_OFFICIAL", "YAHOO_FINANCE", "STOOQ", "FINMIND_FALLBACK"]
    assert fx_chain_names == ["TAIFEX_OFFICIAL", "CBC_OFFICIAL", "YAHOO_FINANCE", "FINMIND_FALLBACK"]


def test_strict_schema_and_reconciliation_checks_pass_for_complete_price_row():
    row = _price_row()

    assert validate_strict_row("price", row) == []
    assert all(check.ok for check in reconciliation_checks("price", row))


def test_fetch_dataset_fails_closed_on_bad_provider_then_uses_valid_fallback(tmp_path: Path):
    context = ProviderContext(trade_date=date(2026, 6, 3), fetched_at=datetime(2026, 6, 3, tzinfo=UTC))
    bad = StaticProvider("BAD_OFFICIAL", _price_row(close=""))
    good = StaticProvider("GOOD_OFFICIAL", _price_row(provider_source="GOOD_OFFICIAL:fixture"))

    result = _fetch_dataset("price", (bad, good), context, tmp_path)

    assert result.ok
    assert result.provider_used == "GOOD_OFFICIAL"
    assert result.failed_providers[0].provider == "BAD_OFFICIAL"
    assert result.provider_health[0].status == "failed"
    assert result.provider_health[1].selected is True
    assert (tmp_path / "price.csv").exists()


def test_fetch_dataset_blocks_when_all_providers_fail(tmp_path: Path):
    context = ProviderContext(trade_date=date(2026, 6, 3), fetched_at=datetime(2026, 6, 3, tzinfo=UTC))

    result = _fetch_dataset("price", (StaticProvider("BROKEN", error=RuntimeError("network unavailable")),), context, tmp_path)

    assert not result.ok
    assert result.status == "failed"
    assert result.validation_errors == ("all providers failed for price",)
    assert not (tmp_path / "price.csv").exists()


def test_finmind_fallback_is_disabled_without_explicit_opt_in():
    context = ProviderContext(trade_date=date(2026, 6, 3), fetched_at=datetime(2026, 6, 3, tzinfo=UTC))

    try:
        FinMindProvider().fetch("price", context)
    except RuntimeError as exc:
        assert "live FinMind fallback disabled" in str(exc)
    else:  # pragma: no cover - explicit failure path for hidden mutation tests.
        raise AssertionError("FinMindProvider must not perform live fetches unless explicitly enabled")


def test_provider_exception_artifacts_include_traceback(tmp_path: Path):
    context = ProviderContext(trade_date=date(2026, 6, 3), fetched_at=datetime(2026, 6, 3, tzinfo=UTC))

    result = _fetch_dataset("price", (StaticProvider("BROKEN", error=RuntimeError("network unavailable")),), context, tmp_path)

    assert not result.ok
    metadata = dict(result.provider_health[0].metadata)
    assert metadata["exception_class"] == "RuntimeError"
    assert metadata["error"] == "network unavailable"
    assert "Traceback (most recent call last)" in metadata["traceback"]
    raw = __import__("json").loads((tmp_path / "_raw" / "price" / "BROKEN.json").read_text(encoding="utf-8"))
    assert raw["exception_class"] == "RuntimeError"
    assert raw["error"] == "network unavailable"
    assert "Traceback (most recent call last)" in raw["traceback"]


def test_finmind_fallback_summary_reports_token_flags_without_secret_values(monkeypatch):
    monkeypatch.delenv("FINMIND_TOKEN", raising=False)
    monkeypatch.setenv("FINMIND_API_TOKEN", "api-token-secret")
    monkeypatch.delenv("TDT_RM_ALLOW_FINMIND_LIVE", raising=False)

    status = _FETCH_MODULE._finmind_fallback_status(False)

    assert status["allow_finmind"] is False
    assert status["finmind_token_present"] is False
    assert status["finmind_api_token_present"] is True
    assert status["token_present"] is True
    assert status["skipped"] is True
    assert "api-token-secret" not in str(status)


def test_chain_finmind_without_opt_in_or_token_fails_closed_and_does_not_succeed(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FINMIND_TOKEN", raising=False)
    monkeypatch.delenv("FINMIND_API_TOKEN", raising=False)
    monkeypatch.delenv("TDT_RM_ALLOW_FINMIND_LIVE", raising=False)
    context = ProviderContext(trade_date=date(2026, 6, 3), fetched_at=datetime(2026, 6, 3, tzinfo=UTC), allow_finmind_live=False)

    result = _fetch_dataset("price", (FinMindProvider(),), context, tmp_path)

    assert not result.ok
    assert result.status == "failed"
    assert result.provider_health[0].provider == "FINMIND_FALLBACK"
    assert "live FinMind fallback disabled" in result.provider_health[0].failure_reason
    assert not (tmp_path / "price.csv").exists()
