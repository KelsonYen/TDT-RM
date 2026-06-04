from __future__ import annotations

import csv
import json
import subprocess
import sys
import urllib.error
from datetime import date
from pathlib import Path

import pytest

from tdt_rm.daily_pipeline import run_daily_pipeline
from tdt_rm.public_data_fetchers import CBCDailyFXSource, PublicDataFetchContext, PublicDataFetcherRegistry, TWSEMarginSource, write_provider_csvs

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


def test_twse_official_redirect_following_handles_307(monkeypatch):
    from tdt_rm import public_data_fetchers as fetchers

    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"data": []}'

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            headers = {"Location": "https://wwwc.twse.com.tw/rwd/en/exchangeReport/FMTQIK?date=20260602&response=json"}
            raise urllib.error.HTTPError(request.full_url, 307, "Temporary Redirect", headers, None)
        return Response()

    monkeypatch.setattr(fetchers.urllib.request, "urlopen", fake_urlopen)
    context = PublicDataFetchContext(as_of=AS_OF)
    payload = fetchers._fetch_json_payload({"endpoint_url_template": "https://www.twse.com.tw/rwd/en/exchangeReport/FMTQIK?date={yyyymmdd}&response=json"}, context)

    assert payload == {"data": []}
    assert calls == [
        "https://www.twse.com.tw/rwd/en/exchangeReport/FMTQIK?date=20260602&response=json",
        "https://wwwc.twse.com.tw/rwd/en/exchangeReport/FMTQIK?date=20260602&response=json",
    ]


def test_twse_margin_source_generates_required_margin_fields(monkeypatch):
    from tdt_rm import public_data_fetchers as fetchers

    balances = {
        date(2026, 5, 28): 1000.0,
        date(2026, 5, 29): 990.0,
        date(2026, 5, 30): 980.0,
        date(2026, 5, 31): 970.0,
        date(2026, 6, 1): 960.0,
        date(2026, 6, 2): 950.0,
    }

    def fake_fetch_any_payload(config, context):
        balance = balances.get(context.as_of)
        if balance is None:
            return {"tables": []}
        return {"tables": [{"fields": ["項目", "今日餘額"], "data": [["融資(交易單位)", f"{balance:,.0f}"], ["融券(交易單位)", "123"], ["融資金額(仟元)", "456,789"]]}]}

    monkeypatch.setattr(fetchers, "_fetch_any_payload", fake_fetch_any_payload)
    source = TWSEMarginSource({"source_id": "twse_margin", "endpoint_url_template": "https://www.twse.com.tw/exchangeReport/MI_MARGN?date={yyyymmdd}&selectType=MS&response=json", "lookback_days": 5})

    result = source.fetch(PublicDataFetchContext(as_of=AS_OF))

    assert result.success
    row = result.rows[0]
    assert result.raw_metadata["latest_margin_balance"] == 950.0
    assert row["margin_balance_5d_flat_or_down"] is True
    assert row["margin_balance_5d_increases"] is False
    assert row["margin_balance_5d_decline_pct"] == 5.0
    assert row["margin_not_retreating"] is False


def test_successful_price_fetch_writes_price_csv(tmp_path):
    results, written = _fetch_write(tmp_path, _config(_source("price_fixture", "price", "taiex_price_response.json")))

    assert results[0].success
    price_path = Path(written.provider_csv_paths["price"])
    assert price_path.name == "price.csv"
    with price_path.open(newline="", encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    assert row["trade_date"] == AS_OF.isoformat()
    assert row["provider_source"] == "price_fixture"
    assert row["source_type"]
    assert row["close"] == "42100"
    assert row["return_60d_pct"] == "6.5"
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
        {**_source("official_price", "price", "official_price_response.json"), "adapter": "twse_fmtqik_price", "min_bars": 61},
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


def test_cbc_daily_fx_parser_generates_official_fx_fields():
    source = CBCDailyFXSource(
        {
            "source_id": "cbc_daily_fx",
            "source_name": "CBC daily FX",
            "provider_category": "fx",
            "adapter": "cbc_daily_fx",
            "fixture_path": str(FIXTURE_DIR / "cbc_fx_response.json"),
            "source_type": "cbc_official_json",
        }
    )

    result = source.fetch(PublicDataFetchContext(as_of=date(2026, 6, 3)))

    assert result.success
    assert result.canonical_fields["date"] == "2026-06-03"
    assert result.canonical_fields["usd_twd"] == 31.8
    assert result.canonical_fields["usd_twd_3d_change_pct"] < 0
    assert result.raw_metadata["official_source"] == "CBC Statistical Database BP01D01en"


def test_twse_fetch_follows_safe_307_redirect(monkeypatch):
    from email.message import Message
    import urllib.error
    import urllib.request

    from tdt_rm.public_data_fetchers import _fetch_json_payload

    calls: list[str] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"data": []}'

    def fake_urlopen(request, timeout):
        url = request.full_url
        calls.append(url)
        if len(calls) == 1:
            headers = Message()
            headers["Location"] = "https://www.twse.com.tw/exchangeReport/FMTQIK?date=20260603&response=json"
            raise urllib.error.HTTPError(url, 307, "Temporary Redirect", headers, None)
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    payload = _fetch_json_payload(
        {
            "source_id": "twse_fmtqik_price",
            "source_type": "twse_official_json",
            "endpoint_url_template": "https://www.twse.com.tw/rwd/en/exchangeReport/FMTQIK?date={yyyymmdd}&response=json",
        },
        PublicDataFetchContext(as_of=date(2026, 6, 3)),
    )

    assert payload == {"data": []}
    assert calls == [
        "https://www.twse.com.tw/rwd/en/exchangeReport/FMTQIK?date=20260603&response=json",
        "https://www.twse.com.tw/exchangeReport/FMTQIK?date=20260603&response=json",
    ]


def test_twse_fetch_rejects_unsafe_307_redirect(monkeypatch):
    from email.message import Message
    import urllib.error
    import urllib.request

    from tdt_rm.public_data_fetchers import _fetch_json_payload

    def fake_urlopen(request, timeout):
        headers = Message()
        headers["Location"] = "https://evil.example/FMTQIK"
        raise urllib.error.HTTPError(request.full_url, 307, "Temporary Redirect", headers, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(ValueError, match="unapproved host"):
        _fetch_json_payload(
            {
                "source_id": "twse_fmtqik_price",
                "source_type": "twse_official_json",
                "endpoint_url_template": "https://www.twse.com.tw/rwd/en/exchangeReport/FMTQIK?date={yyyymmdd}&response=json",
            },
            PublicDataFetchContext(as_of=date(2026, 6, 3)),
        )


def test_live_url_fetch_retries_transient_url_errors(monkeypatch):
    import urllib.error
    import urllib.request

    from tdt_rm.public_data_fetchers import _fetch_json_payload

    calls: list[str] = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"data": [{"ok": true}]}'

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if len(calls) < 3:
            raise urllib.error.URLError("temporary egress failure")
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr("tdt_rm.public_data_fetchers.time.sleep", lambda seconds: None)

    payload = _fetch_json_payload(
        {
            "source_id": "retry_source",
            "source_type": "twse_official_json",
            "endpoint_url_template": "https://www.twse.com.tw/example?date={yyyymmdd}",
        },
        PublicDataFetchContext(as_of=date(2026, 6, 3)),
    )

    assert payload == {"data": [{"ok": True}]}
    assert len(calls) == 3


def test_finmind_sources_are_disabled_unless_explicitly_allowed(monkeypatch):
    from tdt_rm.public_data_fetchers import PublicDataFetcherRegistry

    config = {
        "sources": [
            {
                "source_id": "finmind_price",
                "source_name": "FinMind price fallback",
                "provider_category": "price",
                "adapter": "generic_json",
                "endpoint_url_template": "https://api.finmindtrade.com/api/v4/data",
                "enabled": True,
            }
        ]
    }

    monkeypatch.delenv("TDT_RM_ALLOW_FINMIND_LIVE", raising=False)
    assert PublicDataFetcherRegistry.from_config(config).source_ids() == ()

    monkeypatch.setenv("TDT_RM_ALLOW_FINMIND_LIVE", "true")
    assert PublicDataFetcherRegistry.from_config(config).source_ids() == ("finmind_price",)


def _taifex_options_source_config():
    return {
        "source_id": "taifex_txo_options",
        "source_name": "TAIFEX TXO options PCR and VIX",
        "provider_category": "options",
        "adapter": "taifex_txo_options",
        "endpoint_url_templates": [
            "https://openapi.taifex.com.tw/v1/PutCallRatio",
            "https://openapi.taifex.com.tw/v1/TAIFEXVIX",
        ],
    }


def _option_payload_for_url(url: str):
    if "PutCallRatio" in url:
        return [{"Date": AS_OF.isoformat(), "Put/Call Ratio": "1.15", "Put Volume": "1150", "Call Volume": "1000"}]
    if "TAIFEXVIX" in url:
        return [{"Date": AS_OF.isoformat(), "TAIFEX VIX": "21.5"}]
    raise AssertionError(url)


@pytest.mark.parametrize(
    ("failing_endpoint", "expected_fields", "expected_issue_count"),
    [
        ("TAIFEXVIX", {"txo_put_call_ratio", "txo_put_volume", "txo_call_volume"}, 1),
        ("PutCallRatio", {"taifex_vix"}, 1),
        (None, {"txo_put_call_ratio", "txo_put_volume", "txo_call_volume", "taifex_vix"}, 0),
    ],
)
def test_taifex_options_fetch_preserves_successful_endpoint_when_peer_endpoint_fails(monkeypatch, failing_endpoint, expected_fields, expected_issue_count):
    from tdt_rm import public_data_fetchers as fetchers
    from tdt_rm.public_data_fetchers import TAIFEXTXOOptionsSource

    def fake_fetch_any_payload(config, context):
        url = str(config.get("endpoint_url_template"))
        if failing_endpoint and failing_endpoint in url:
            raise RuntimeError(f"{failing_endpoint} unavailable")
        return _option_payload_for_url(url)

    monkeypatch.setattr(fetchers, "_fetch_any_payload", fake_fetch_any_payload)

    result = TAIFEXTXOOptionsSource(_taifex_options_source_config()).fetch(PublicDataFetchContext(as_of=AS_OF))

    assert result.success
    assert {field for field in expected_fields if field in result.rows[0]} == expected_fields
    assert len(result.issues) == expected_issue_count
    endpoint_statuses = result.raw_metadata["endpoints"]
    assert len(endpoint_statuses) == 2
    if failing_endpoint:
        failed = [item for item in endpoint_statuses if failing_endpoint in item["endpoint"]]
        assert failed and failed[0]["status"] == "failed"


def test_taifex_options_fetch_fails_when_both_endpoints_fail(monkeypatch):
    from tdt_rm import public_data_fetchers as fetchers
    from tdt_rm.public_data_fetchers import TAIFEXTXOOptionsSource

    def fake_fetch_any_payload(config, context):
        raise RuntimeError(f"{config.get('endpoint_url_template')} unavailable")

    monkeypatch.setattr(fetchers, "_fetch_any_payload", fake_fetch_any_payload)

    result = TAIFEXTXOOptionsSource(_taifex_options_source_config()).fetch(PublicDataFetchContext(as_of=AS_OF))

    assert not result.success
    assert result.status == "failed"
    assert [item["status"] for item in result.raw_metadata["endpoints"]] == ["failed", "failed"]
    assert any(issue.code == "row_missing" for issue in result.issues)


def test_twse_t86_compact_foreign_flow_alias_parses_non_null():
    from tdt_rm.public_data_fetchers import _parse_t86_foreign_flow

    row = _parse_t86_foreign_flow(
        {"data": [{"證券代號": "2330", "外陸資買賣超股數(不含自營商)": "1,234"}]},
        AS_OF,
    )

    assert row is not None
    assert row["foreign_spot_net_buy"] == 1234.0
    assert row["foreign_spot_net_sell"] is False


def test_twse_mi_index_breadth_type_rows_parse_market_and_stock_counts():
    from tdt_rm.public_data_fetchers import _parse_twse_breadth

    row = _parse_twse_breadth(
        {
            "data": [
                {"類型": "上漲", "整體市場": "634", "股票": "611"},
                {"類型": "下跌", "整體市場": "311", "股票": "298"},
            ]
        },
        AS_OF,
    )

    assert row is not None
    assert row["advancing_issues"] == 634
    assert row["declining_issues"] == 311


def test_taifex_nested_daily_market_report_fut_parses_txf_row():
    from tdt_rm.public_data_fetchers import _parse_taifex_futures

    row = _parse_taifex_futures(
        [[{"ContractCode": "TXF", "Close": "21,000", "SettlementPrice": "21,010", "Volume": "12,345", "OpenInterest": "67,890"}]],
        AS_OF,
    )

    assert row is not None
    assert row["txf_close"] == 21000.0
    assert row["txf_settlement"] == 21010.0
    assert row["txf_volume"] == 12345.0
    assert row["txf_open_interest"] == 67890.0
    assert row["futures_source_contract"] == "TXF"


def test_taifex_put_call_ratio_compact_fields_parse_pcr():
    from tdt_rm.public_data_fetchers import _parse_taifex_options

    row = _parse_taifex_options(
        [{"PutCallVolumeRatio": "118.25", "PutVolume": "11825", "CallVolume": "10000"}],
        AS_OF,
    )

    assert row["txo_put_call_ratio"] == 118.25
    assert row["txo_put_volume"] == 11825.0
    assert row["txo_call_volume"] == 10000.0


def test_taifex_nested_list_payload_flattens_to_mapping_rows_only():
    from tdt_rm.public_data_fetchers import _payload_rows

    rows = _payload_rows([[{"ContractCode": "TXF"}, {"ContractCode": "MXF"}], "ignored", [[{"ContractCode": "TXO"}]]])

    assert rows == [{"ContractCode": "TXF"}, {"ContractCode": "MXF"}, {"ContractCode": "TXO"}]
