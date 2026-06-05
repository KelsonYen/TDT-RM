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


def test_finmind_client_get_allows_optional_end_date():
    module = _load_finmind_module()

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"status": 200, "data": []}'

    class Opener:
        def __init__(self):
            self.urls = []

        def open(self, request, timeout):
            self.urls.append(request.full_url)
            return Response()

    opener = Opener()
    client = module.FinMindClient(None, sleep_seconds=0, opener=opener)

    assert client.get("TaiwanStockPrice", start_date=module.date(2026, 6, 4), end_date=None) == []
    query = module.urllib.parse.parse_qs(module.urllib.parse.urlparse(opener.urls[0]).query)
    assert query["dataset"] == ["TaiwanStockPrice"]
    assert query["start_date"] == ["2026-06-04"]
    assert "end_date" not in query


def test_build_breadth_uses_single_date_all_universe_requests_and_counts_advancers_decliners():
    module = _load_finmind_module()

    class FakeClient:
        def __init__(self):
            self.calls = []

        def get(self, dataset, *, start_date, end_date=None, data_id=None):
            self.calls.append((dataset, start_date, end_date, data_id))
            if dataset == "TaiwanStockTotalReturnIndex" and data_id == "TAIEX":
                return [
                    {"date": "2026-06-03", "stock_id": "TAIEX", "price": 101},
                    {"date": "2026-06-04", "stock_id": "TAIEX", "price": 100},
                ]
            if dataset == "TaiwanStockPrice" and data_id is None and end_date is None:
                if start_date == module.date(2026, 6, 3):
                    return [
                        {"date": "2026-06-03", "stock_id": "1101", "close": 10},
                        {"date": "2026-06-03", "stock_id": "1102", "close": 20},
                        {"date": "2026-06-03", "stock_id": "1103", "close": 30},
                        {"date": "2026-06-03", "stock_id": "1104", "close": 40},
                    ]
                if start_date == module.date(2026, 6, 4):
                    return [
                        {"date": "2026-06-04", "stock_id": "1101", "close": 11},
                        {"date": "2026-06-04", "stock_id": "1102", "close": 19},
                        {"date": "2026-06-04", "stock_id": "1103", "close": 30},
                        {"date": "2026-06-04", "stock_id": "1105", "close": 50},
                    ]
            return []

    client = FakeClient()
    row, source = module.build_breadth(
        client,
        module.date(2026, 6, 4),
        module.date(2026, 1, 1),
        "2026-06-05T00:00:00Z",
    )

    assert source == "TaiwanStockPrice:listed_universe"
    assert row["advancing_issues"] == 1
    assert row["declining_issues"] == 1
    assert row["index_down"] is True
    assert client.calls == [
        ("TaiwanStockTotalReturnIndex", module.date(2026, 1, 1), module.date(2026, 6, 4), "TAIEX"),
        ("TaiwanStockPrice", module.date(2026, 6, 3), None, None),
        ("TaiwanStockPrice", module.date(2026, 6, 4), None, None),
    ]
    assert all(
        not (dataset == "TaiwanStockPrice" and end_date == module.date(2026, 6, 4) and data_id is None)
        for dataset, _start_date, end_date, data_id in client.calls
    )


def test_build_breadth_reports_finmind_all_date_entitlement_requirement():
    module = _load_finmind_module()

    class FakeClient:
        def get(self, dataset, *, start_date, end_date=None, data_id=None):
            if dataset == "TaiwanStockTotalReturnIndex":
                return [
                    {"date": "2026-06-03", "stock_id": "TAIEX", "price": 101},
                    {"date": "2026-06-04", "stock_id": "TAIEX", "price": 100},
                ]
            raise RuntimeError("status=402 permission denied")

    try:
        module.build_breadth(
            FakeClient(),
            module.date(2026, 6, 4),
            module.date(2026, 1, 1),
            "2026-06-05T00:00:00Z",
        )
    except RuntimeError as exc:
        assert "FinMind backer/sponsor all-date TaiwanStockPrice access is required" in str(exc)
        assert "status=402 permission denied" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
