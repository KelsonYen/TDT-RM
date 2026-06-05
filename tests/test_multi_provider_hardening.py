from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
import importlib.util

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "fetch_daily_data_multi_provider.py"
_SPEC = importlib.util.spec_from_file_location("fetch_daily_data_multi_provider", _SCRIPT_PATH)
assert _SPEC and _SPEC.loader
_FETCH_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FETCH_MODULE)
_fetch_dataset = _FETCH_MODULE._fetch_dataset
_allow_finmind_live = _FETCH_MODULE._allow_finmind_live
_provider_chains = _FETCH_MODULE._provider_chains
from tdt_rm.data_providers import ProviderContext, ProviderResult  # noqa: E402
from tdt_rm.data_providers.finmind import FinMindProvider  # noqa: E402
from tdt_rm.data_providers.normalizers import REAL_SOURCE_TYPE, reconciliation_checks, validate_strict_row  # noqa: E402


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


def test_finmind_live_opt_in_accepts_cli_or_env(monkeypatch):
    monkeypatch.delenv("TDT_RM_ALLOW_FINMIND_LIVE", raising=False)

    assert _allow_finmind_live(SimpleNamespace(allow_finmind_live=False)) is False
    assert _allow_finmind_live(SimpleNamespace(allow_finmind_live=True)) is True

    monkeypatch.setenv("TDT_RM_ALLOW_FINMIND_LIVE", "true")
    assert _allow_finmind_live(SimpleNamespace(allow_finmind_live=False)) is True

    monkeypatch.setenv("TDT_RM_ALLOW_FINMIND_LIVE", "false")
    assert _allow_finmind_live(SimpleNamespace(allow_finmind_live=False)) is False

    monkeypatch.delenv("TDT_RM_ALLOW_FINMIND_LIVE", raising=False)
    assert _allow_finmind_live(SimpleNamespace(allow_finmind_live=False)) is False


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


def test_provider_chain_adds_yahoo_representative_breadth_before_finmind():
    chains = _provider_chains(None)
    breadth_chain_names = [provider.name for provider in chains["breadth"]]

    assert breadth_chain_names == ["TWSE_OFFICIAL", "YAHOO_FINANCE", "FINMIND_FALLBACK"]


def test_yahoo_representative_breadth_counts_and_metadata(tmp_path: Path, monkeypatch):
    from tdt_rm.market_data import MarketPriceBar
    from tdt_rm.data_providers.yahoo import YahooProvider
    import tdt_rm.data_providers.yahoo as yahoo_module

    universe = tmp_path / "breadth_universe.json"
    universe.write_text('{"symbols": ["2330", "2454", "2317", "2382"]}\n', encoding="utf-8")

    def fake_bars(symbol: str, start: date, end: date, timeout: int):
        closes = {
            "^TWII": (100.0, 99.0),
            "2330.TW": (10.0, 11.0),
            "2454.TW": (20.0, 19.0),
            "2317.TW": (30.0, 30.0),
            "2382.TW": (40.0, 42.0),
        }[symbol]
        return [
            MarketPriceBar(observed_at=date(2026, 6, 3), close=closes[0], turnover_amount=0.0),
            MarketPriceBar(observed_at=date(2026, 6, 4), close=closes[1], turnover_amount=0.0),
        ]

    monkeypatch.setattr(yahoo_module, "_yahoo_bars", fake_bars)
    context = ProviderContext(
        trade_date=date(2026, 6, 4),
        fetched_at=datetime(2026, 6, 5, tzinfo=UTC),
        breadth_universe_config=universe,
    )

    result = YahooProvider().fetch("breadth", context)

    assert result.provider == "YAHOO_FINANCE:representative_universe"
    assert result.row["advancing_issues"] == 2
    assert result.row["declining_issues"] == 1
    assert result.row["index_down"] is True
    assert validate_strict_row("breadth", result.row) == []
    assert result.raw_metadata["breadth_source_scope"] == "representative_universe"
    assert result.raw_metadata["unchanged_count"] == 1
    assert result.raw_metadata["total_count"] == 4
    assert result.raw_metadata["advance_decline_ratio"] == 2.0


def test_non_sponsor_finmind_breadth_falls_through_to_representative_fallback(tmp_path: Path, monkeypatch):
    from tdt_rm.market_data import MarketPriceBar
    from tdt_rm.data_providers.yahoo import YahooProvider
    import tdt_rm.data_providers.yahoo as yahoo_module

    monkeypatch.setenv("FINMIND_TOKEN", "regular-token")
    monkeypatch.delenv("FINMIND_API_TOKEN", raising=False)
    monkeypatch.delenv("TDT_RM_FINMIND_SPONSOR_ACCESS", raising=False)
    monkeypatch.delenv("FINMIND_SPONSOR_ACCESS", raising=False)

    universe = tmp_path / "breadth_universe.json"
    universe.write_text('{"symbols": ["2330", "2454"]}\n', encoding="utf-8")

    def fake_bars(symbol: str, start: date, end: date, timeout: int):
        closes = {
            "^TWII": (100.0, 101.0),
            "2330.TW": (10.0, 11.0),
            "2454.TW": (20.0, 19.0),
        }[symbol]
        return [
            MarketPriceBar(observed_at=date(2026, 6, 3), close=closes[0], turnover_amount=0.0),
            MarketPriceBar(observed_at=date(2026, 6, 4), close=closes[1], turnover_amount=0.0),
        ]

    monkeypatch.setattr(yahoo_module, "_yahoo_bars", fake_bars)
    context = ProviderContext(
        trade_date=date(2026, 6, 4),
        fetched_at=datetime(2026, 6, 5, tzinfo=UTC),
        allow_finmind_live=True,
        breadth_universe_config=universe,
    )

    result = _fetch_dataset("breadth", (FinMindProvider(), YahooProvider()), context, tmp_path)

    assert result.ok
    assert result.provider_health[0].provider == "FINMIND_FALLBACK"
    assert "requires backer/sponsor" in result.provider_health[0].failure_reason
    assert result.provider_health[1].provider == "YAHOO_FINANCE"
    assert result.provider_health[1].selected is True
    assert result.provider_used == "YAHOO_FINANCE:representative_universe"
    assert (tmp_path / "breadth.csv").exists()
