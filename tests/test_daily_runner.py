import json
from datetime import UTC, date, datetime
from pathlib import Path

from tdt_rm import MarketPriceBar
from tdt_rm.daily_runner import (
    ETFExitHook,
    build_daily_payload,
    parse_twse_taiex_payload,
    render_daily_markdown,
    run_daily_production,
)


class FakeFetcher:
    def __init__(self, bars):
        self.bars = bars
        self.calls = []

    def fetch_bars(self, *, as_of: date, min_bars: int):
        self.calls.append({"as_of": as_of, "min_bars": min_bars})
        return self.bars


def sample_bars(count=70):
    return [
        MarketPriceBar(
            observed_at=date(2026, 1, 1).fromordinal(date(2026, 1, 1).toordinal() + index),
            close=10000 + index * 10,
            turnover_amount=1_000_000 + index,
        )
        for index in range(count)
    ]


def test_parse_twse_taiex_payload_accepts_roc_dates_and_commas():
    payload = {
        "fields": ["Date", "Opening Index", "Highest Index", "Lowest Index", "Closing Index"],
        "data": [["115/01/05", "18,000.00", "18,100.00", "17,900.00", "18,050.50"]],
    }

    bars = parse_twse_taiex_payload(payload)

    assert bars[0].observed_at == date(2026, 1, 5)
    assert bars[0].close == 18050.50
    assert bars[0].open == 18000.00


def test_build_daily_payload_includes_required_daily_scores_and_etf_exit_placeholder():
    payload = build_daily_payload(
        sample_bars(),
        timestamp=datetime(2026, 1, 15, 8, 30, tzinfo=UTC),
        etf_exit_hook=ETFExitHook(payload={"future_field": "reserved"}),
    )

    assert payload["timestamp"] == "2026-01-15T08:30:00Z"
    assert payload["model_version"] == "TDT-RM V5.1.4"
    assert payload["market_regime"] in {"risk-on", "watch", "caution", "risk-off", "crash-risk"}
    assert {"TCWRS", "MHS", "ETI-5", "Tail Risk", "BCD", "CP"} == set(payload["scores"])
    assert payload["tcwrs"] == payload["scores"]["TCWRS"]
    assert payload["mhs"] == 0.0
    assert payload["eti_5"] == payload["scores"]["ETI-5"]
    assert payload["tail_risk"] == payload["scores"]["Tail Risk"]
    assert payload["bcd"] == payload["scores"]["BCD"]
    assert payload["cp"] == payload["scores"]["CP"]
    assert payload["signal"]
    assert payload["etf_exit"]["status"] == "not_integrated"
    assert payload["etf_exit"]["payload"] == {"future_field": "reserved"}


def test_render_daily_markdown_contains_required_report_sections():
    payload = build_daily_payload(sample_bars(), timestamp=datetime(2026, 1, 15, tzinfo=UTC))

    report = render_daily_markdown(payload)

    assert report.splitlines()[0] == "2026/03/11 台股雙溫度計風控報告"
    assert "今日燈號：" in report
    assert "股票曝險上限：" in report
    assert "■ 核心結論" in report
    assert "■ ETI-5 明細" in report
    assert "■ 今日動作" in report
    assert "|" not in report


def test_run_daily_production_writes_json_and_markdown(tmp_path: Path):
    fetcher = FakeFetcher(sample_bars())

    result = run_daily_production(
        as_of=date(2026, 3, 31),
        output_dir=tmp_path,
        fetcher=fetcher,
        timestamp=datetime(2026, 3, 31, 9, 0, tzinfo=UTC),
    )

    assert fetcher.calls == [{"as_of": date(2026, 3, 31), "min_bars": 61}]
    assert result.json_path.exists()
    assert result.markdown_path.exists()
    assert result.json_path.parent == tmp_path
    assert result.markdown_path.read_text(encoding="utf-8").startswith("2026/03/11 台股雙溫度計風控報告")
    assert '"signal"' in result.json_path.read_text(encoding="utf-8")


def test_run_daily_production_optionally_writes_manifest(tmp_path: Path):
    fetcher = FakeFetcher(sample_bars())

    result = run_daily_production(
        as_of=date(2026, 3, 11),
        output_dir=tmp_path,
        fetcher=fetcher,
        timestamp=datetime(2026, 3, 11, 9, 0, tzinfo=UTC),
        write_manifest=True,
        command="pytest daily runner",
        git_sha="abc123",
    )

    assert result.manifest_path is not None
    assert result.manifest_path.exists()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["artifact_paths"] == {"json": str(result.json_path), "markdown": str(result.markdown_path)}
    assert manifest["validation_status"] == "warning"
    assert manifest["command"] == "pytest daily runner"
    assert manifest["git_sha"] == "abc123"
