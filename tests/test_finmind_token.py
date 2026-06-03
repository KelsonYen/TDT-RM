import importlib.util
import sys
from pathlib import Path


def _load_finmind_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "fetch_daily_data_finmind.py"
    spec = importlib.util.spec_from_file_location("fetch_daily_data_finmind", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_finmind_api_token_env_alias(monkeypatch):
    module = _load_finmind_module()
    monkeypatch.delenv("FINMIND_TOKEN", raising=False)
    monkeypatch.setenv("FINMIND_API_TOKEN", "api-token")

    assert module.finmind_token_from_env() == "api-token"


def test_finmind_token_takes_precedence(monkeypatch):
    module = _load_finmind_module()
    monkeypatch.setenv("FINMIND_TOKEN", "primary-token")
    monkeypatch.setenv("FINMIND_API_TOKEN", "api-token")

    assert module.finmind_token_from_env() == "primary-token"


def test_finmind_taiex_fetch_prefers_total_return_index():
    module = _load_finmind_module()

    class FakeClient:
        def __init__(self):
            self.calls = []

        def get(self, dataset, *, start_date, end_date, data_id=None):
            self.calls.append((dataset, data_id))
            if dataset == "TaiwanStockTotalReturnIndex" and data_id == "TAIEX":
                return [
                    {"date": "2026-01-02", "stock_id": "TAIEX", "price": 100},
                    {"date": "2026-01-03", "stock_id": "TAIEX", "price": 101},
                ]
            return []

    client = FakeClient()
    rows = module.fetch_price_rows(
        client,
        start=module.date(2026, 1, 1),
        end=module.date(2026, 1, 3),
        data_id="TAIEX",
    )

    assert rows[-1]["price"] == 101
    assert client.calls == [("TaiwanStockTotalReturnIndex", "TAIEX")]


def test_price_bars_accept_finmind_index_price_field():
    module = _load_finmind_module()

    bars = module.price_bars_for(
        [
            {"date": "2026-01-02", "stock_id": "TAIEX", "price": "100.5"},
            {"date": "2026-01-03", "stock_id": "TAIEX", "price": "101.25"},
        ],
        module.date(2026, 1, 3),
    )

    assert [bar.close for bar in bars] == [100.5, 101.25]
    assert all(bar.turnover_amount == 0 for bar in bars)


def _finmind_proxy_args(**overrides):
    values = {"direct_finmind": False, "finmind_https_proxy": None, "finmind_http_proxy": None}
    values.update(overrides)
    return type("Args", (), values)()


def test_finmind_direct_env_builds_custom_opener(monkeypatch):
    module = _load_finmind_module()
    monkeypatch.setenv("FINMIND_DIRECT", "1")

    assert module.build_finmind_opener(_finmind_proxy_args()) is not None


def test_finmind_specific_proxy_builds_custom_opener(monkeypatch):
    module = _load_finmind_module()
    monkeypatch.delenv("FINMIND_DIRECT", raising=False)
    monkeypatch.setenv("FINMIND_HTTPS_PROXY", "http://finmind-proxy:8080")

    assert module.build_finmind_opener(_finmind_proxy_args()) is not None


def test_default_finmind_opener_uses_urllib_environment(monkeypatch):
    module = _load_finmind_module()
    monkeypatch.delenv("FINMIND_DIRECT", raising=False)
    monkeypatch.delenv("FINMIND_HTTPS_PROXY", raising=False)
    monkeypatch.delenv("FINMIND_HTTP_PROXY", raising=False)

    assert module.build_finmind_opener(_finmind_proxy_args()) is None
