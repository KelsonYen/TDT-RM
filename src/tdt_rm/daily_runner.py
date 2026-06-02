"""Daily production runner for TDT-RM V5.1.4.

This module is intentionally a thin orchestration layer: it downloads public
TAIEX price bars, derives the minimum price features needed by the existing
V5.1.4 scoring modules, and writes daily JSON/Markdown artifacts.  It does not
change model scoring logic.
"""

from __future__ import annotations

import json
import math
import statistics
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .crash_probability import CrashProbabilityInput, score_crash_probability
from .decision_matrix import (
    BearTrendInput,
    DecisionMatrixInput,
    score_bear_trend_filter,
    resolve_five_light_signal,
)
from .eti5 import ETI5Input, score_eti5
from .market_data import MarketPriceBar, derive_price_features
from .tcwrs import TCWRSInput, score_tcwrs

DEFAULT_OUTPUT_DIR = Path("outputs/daily")
DEFAULT_TWSE_URL = "https://www.twse.com.tw/rwd/en/TAIEX/MI_5MINS_HIST"
DEFAULT_MIN_BARS = 61
DEFAULT_LOOKBACK_MONTHS = 12
MODEL_VERSION = "TDT-RM V5.1.4"


class DailyDataFetcher(Protocol):
    """Protocol for future data vendors or ETF Exit-aware data fetchers."""

    def fetch_bars(self, *, as_of: date, min_bars: int) -> Sequence[MarketPriceBar]:
        """Return chronological Taiwan market bars ending at the latest available date."""


@dataclass(frozen=True)
class ETFExitHook:
    """Placeholder contract for future ETF Exit integration.

    The daily runner records this metadata today but does not apply ETF-specific
    exit logic.  Future integrations can replace this hook with a populated ETF
    exit result without changing the daily artifact shape.
    """

    enabled: bool = False
    status: str = "not_integrated"
    notes: str = "Reserved for future ETF Exit integration; no ETF exit logic applied."
    payload: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "status": self.status,
            "notes": self.notes,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class TWSETAIEXFetcher:
    """Download latest TAIEX index bars from the public TWSE monthly endpoint."""

    base_url: str = DEFAULT_TWSE_URL
    lookback_months: int = DEFAULT_LOOKBACK_MONTHS
    timeout_seconds: float = 20.0

    def fetch_bars(self, *, as_of: date, min_bars: int) -> Sequence[MarketPriceBar]:
        bars: dict[date, MarketPriceBar] = {}
        for month_start in _month_starts_desc(as_of, self.lookback_months):
            for bar in self._fetch_month(month_start):
                if _coerce_date(bar.observed_at) <= as_of:
                    bars[_coerce_date(bar.observed_at)] = bar
            if len(bars) >= min_bars and bars:
                latest = max(bars)
                oldest_needed = sorted(bars)[-min_bars]
                if oldest_needed <= latest:
                    break
        ordered = [bars[key] for key in sorted(bars)]
        if len(ordered) < min_bars:
            raise ValueError(
                f"TWSE download returned {len(ordered)} usable bars; at least {min_bars} are required"
            )
        return ordered[-min_bars:]

    def _fetch_month(self, month_start: date) -> Sequence[MarketPriceBar]:
        query = urllib.parse.urlencode(
            {"date": month_start.strftime("%Y%m%d"), "response": "json"}
        )
        request = urllib.request.Request(
            f"{self.base_url}?{query}",
            headers={"User-Agent": "TDT-RM daily runner"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8-sig"))
        return parse_twse_taiex_payload(payload)


@dataclass(frozen=True)
class DailyRunResult:
    """Paths and payload emitted by one daily production run."""

    json_path: Path
    markdown_path: Path
    payload: Mapping[str, Any]


def run_daily_production(
    *,
    as_of: date | None = None,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    fetcher: DailyDataFetcher | None = None,
    timestamp: datetime | None = None,
    etf_exit_hook: ETFExitHook | None = None,
) -> DailyRunResult:
    """Download latest Taiwan market data, run V5.1.4, and save daily artifacts."""

    run_timestamp = timestamp or datetime.now(UTC)
    effective_as_of = as_of or run_timestamp.date()
    data_fetcher = fetcher or TWSETAIEXFetcher()
    bars = list(data_fetcher.fetch_bars(as_of=effective_as_of, min_bars=DEFAULT_MIN_BARS))
    if len(bars) < DEFAULT_MIN_BARS:
        raise ValueError(f"at least {DEFAULT_MIN_BARS} bars are required")

    payload = build_daily_payload(
        bars,
        timestamp=run_timestamp,
        etf_exit_hook=etf_exit_hook or ETFExitHook(),
    )
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    trade_date = payload["trade_date"]
    json_path = destination / f"tdt_rm_daily_{trade_date}.json"
    markdown_path = destination / f"tdt_rm_daily_{trade_date}.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_daily_markdown(payload), encoding="utf-8")
    return DailyRunResult(json_path=json_path, markdown_path=markdown_path, payload=payload)


def build_daily_payload(
    bars: Sequence[MarketPriceBar],
    *,
    timestamp: datetime | None = None,
    etf_exit_hook: ETFExitHook | None = None,
) -> dict[str, Any]:
    """Run existing V5.1.4 modules against already-downloaded chronological bars."""

    if len(bars) < DEFAULT_MIN_BARS:
        raise ValueError(f"at least {DEFAULT_MIN_BARS} bars are required")
    ordered = sorted(bars, key=lambda bar: _coerce_date(bar.observed_at))
    features = derive_price_features(ordered)
    closes = [float(bar.close) for bar in ordered]
    close = float(features["close"])
    ma20 = float(features["ma20"])
    ma60 = float(features["ma60"])
    previous_ma60 = _moving_average(closes[:-1], 60)
    one_day_return = float(features["one_day_return_pct"])
    two_day_return = float(features["two_day_return_pct"])
    five_day_return = _pct_change(closes[-6], closes[-1]) if len(closes) >= 6 else 0.0
    return_60d = _pct_change(closes[-61], closes[-1]) if len(closes) >= 61 else 0.0
    consecutive_down_days = _consecutive_down_days(closes)
    close_below_ma20_days = _consecutive_below_ma20(closes)
    peak = max(closes)
    drawdown = max(0.0, -_pct_change(peak, close))
    tail_risk = _price_proxy_tail_risk(closes, drawdown, one_day_return, two_day_return)
    bcd = _price_proxy_bcd(close, ma20, drawdown, consecutive_down_days)
    mhs = 0.0

    tcwrs = score_tcwrs(
        TCWRSInput(
            close=close,
            ma5=float(features["ma5"]),
            ma20=ma20,
            ma60=ma60,
            ma20_slope=float(features["ma20_slope"]),
            close_below_ma20_consecutive_days=close_below_ma20_days,
            one_day_return_pct=one_day_return,
            two_day_return_pct=two_day_return,
            close_is_black=one_day_return < -1.5,
            long_black_candle=one_day_return < -2.0,
            index_5d_return_pct=five_day_return,
            margin_balance_5d_decline_pct=max(0.0, -five_day_return / 2.0),
            index_down=one_day_return < 0,
            declining_issues_significantly_expand=one_day_return < -1.5,
            declining_issues_significantly_gt_advancing=one_day_return < -0.75,
            declining_gt_advancing_consecutive_days=consecutive_down_days,
            count_main_7_below_ma20=5 if close < ma20 else 0,
        )
    )
    eti5 = score_eti5(
        ETI5Input(
            close=close,
            ma20=ma20,
            available_components={"ETI-1"},
        )
    )
    cp = score_crash_probability(
        CrashProbabilityInput(
            tcwrs=tcwrs.total_score,
            eti5_total=eti5.eti_score,
            tail_risk=tail_risk,
            bcd=bcd,
        )
    )
    bear_trend = score_bear_trend_filter(
        BearTrendInput(
            close=close,
            ma20=ma20,
            ma60=ma60,
            previous_ma60=previous_ma60,
            return_60d_pct=return_60d,
        )
    )
    decision = resolve_five_light_signal(
        DecisionMatrixInput(
            tcwrs=tcwrs.total_score,
            eti5_total=eti5.eti_score,
            tail_risk=tail_risk,
            bcd=bcd,
            taiex=close,
            ma20=ma20,
            consecutive_down_days=consecutive_down_days,
            mhs=mhs,
            cp_score=cp.cp_score,
            eti_available_count=eti5.eti_available_count,
        ),
        bear_trend=bear_trend,
    )
    market_regime = classify_market_regime(decision.signal, tcwrs.total_score, close, ma20, ma60)
    run_timestamp = timestamp or datetime.now(UTC)
    etf_hook = etf_exit_hook or ETFExitHook()

    return {
        "timestamp": _iso_timestamp(run_timestamp),
        "model_version": MODEL_VERSION,
        "trade_date": str(features["observed_at"]),
        "market_regime": market_regime,
        "tcwrs": tcwrs.total_score,
        "mhs": mhs,
        "eti_5": eti5.eti_score,
        "tail_risk": round(tail_risk, 2),
        "bcd": round(bcd, 2),
        "cp": round(cp.cp_score, 2),
        "cp_level": cp.cp_level,
        "signal": decision.signal,
        "equity_exposure_limit": decision.equity_exposure_limit,
        "inputs": {
            "close": round(close, 2),
            "ma5": round(float(features["ma5"]), 2),
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2),
            "ma20_slope": round(float(features["ma20_slope"]), 4),
            "one_day_return_pct": round(one_day_return, 4),
            "two_day_return_pct": round(two_day_return, 4),
            "five_day_return_pct": round(five_day_return, 4),
            "return_60d_pct": round(return_60d, 4),
            "consecutive_down_days": consecutive_down_days,
            "close_below_ma20_consecutive_days": close_below_ma20_days,
        },
        "scores": {
            "TCWRS": tcwrs.total_score,
            "MHS": mhs,
            "ETI-5": eti5.eti_score,
            "Tail Risk": round(tail_risk, 2),
            "BCD": round(bcd, 2),
            "CP": round(cp.cp_score, 2),
        },
        "traces": {
            "tcwrs": tcwrs.as_dict(),
            "eti_5": eti5.as_dict(),
            "crash_probability": cp.as_dict(),
            "bear_trend": bear_trend.as_dict(),
            "decision_matrix": decision.as_dict(),
        },
        "data": {
            "source": "TWSE TAIEX MI_5MINS_HIST public monthly index endpoint",
            "latest_bar_date": str(features["observed_at"]),
            "bar_count": len(ordered),
            "status": "price_only_provisional",
            "limitations": [
                "ETI-5 is limited to the available ETI-1 price component.",
                "Tail Risk and BCD use existing price-only production proxies until formal modules exist.",
                "MHS has no standalone scorer in this repository and is set to 0.0.",
            ],
        },
        "etf_exit": etf_hook.as_dict(),
    }


def render_daily_markdown(payload: Mapping[str, Any]) -> str:
    """Render the daily JSON payload as an operator-friendly Markdown report."""

    scores = payload["scores"]
    inputs = payload["inputs"]
    data = payload["data"]
    etf_exit = payload["etf_exit"]
    return "\n".join(
        [
            f"# TDT-RM Daily Report — {payload['trade_date']}",
            "",
            f"- Timestamp: `{payload['timestamp']}`",
            f"- Model: `{payload['model_version']}`",
            f"- Market regime: **{payload['market_regime']}**",
            f"- Signal: **{payload['signal']}**",
            f"- Equity exposure limit: **{payload['equity_exposure_limit']}**",
            "",
            "## Scores",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
            f"| TCWRS | {scores['TCWRS']} |",
            f"| MHS | {scores['MHS']} |",
            f"| ETI-5 | {scores['ETI-5']} |",
            f"| Tail Risk | {scores['Tail Risk']} |",
            f"| BCD | {scores['BCD']} |",
            f"| CP | {scores['CP']} |",
            "",
            "## Market Inputs",
            "",
            "| Input | Value |",
            "| --- | ---: |",
            f"| Close | {inputs['close']} |",
            f"| MA5 | {inputs['ma5']} |",
            f"| MA20 | {inputs['ma20']} |",
            f"| MA60 | {inputs['ma60']} |",
            f"| MA20 slope | {inputs['ma20_slope']} |",
            f"| 1D return % | {inputs['one_day_return_pct']} |",
            f"| 2D return % | {inputs['two_day_return_pct']} |",
            f"| 5D return % | {inputs['five_day_return_pct']} |",
            f"| 60D return % | {inputs['return_60d_pct']} |",
            f"| Consecutive down days | {inputs['consecutive_down_days']} |",
            f"| Consecutive closes below MA20 | {inputs['close_below_ma20_consecutive_days']} |",
            "",
            "## Data Notes",
            "",
            f"- Source: {data['source']}",
            f"- Latest bar date: {data['latest_bar_date']}",
            f"- Bar count: {data['bar_count']}",
            f"- Data status: `{data['status']}`",
            *[f"- {note}" for note in data["limitations"]],
            "",
            "## Future ETF Exit Integration",
            "",
            f"- Enabled: `{etf_exit['enabled']}`",
            f"- Status: `{etf_exit['status']}`",
            f"- Notes: {etf_exit['notes']}",
            "",
        ]
    )


def parse_twse_taiex_payload(payload: Mapping[str, Any]) -> list[MarketPriceBar]:
    """Parse TWSE MI_5MINS_HIST JSON payload into chronological price bars."""

    rows = payload.get("data") or payload.get("tables", [{}])[0].get("data") or []
    fields = [str(field).strip().lower() for field in payload.get("fields", [])]
    parsed: list[MarketPriceBar] = []
    for row in rows:
        values = list(row)
        if len(values) < 2:
            continue
        observed_at = _parse_twse_date(_field_value(values, fields, "date", 0))
        close = _parse_number(_field_value(values, fields, "closing index", -1))
        open_value = _optional_number(_field_value(values, fields, "opening index", 1))
        high = _optional_number(_field_value(values, fields, "highest index", 2))
        low = _optional_number(_field_value(values, fields, "lowest index", 3))
        parsed.append(
            MarketPriceBar(
                observed_at=observed_at,
                close=close,
                turnover_amount=0.0,
                open=open_value,
                high=high,
                low=low,
            )
        )
    return sorted(parsed, key=lambda bar: _coerce_date(bar.observed_at))


def classify_market_regime(signal: str, tcwrs: float, close: float, ma20: float, ma60: float) -> str:
    """Return a stable high-level label for daily reports without changing signals."""

    if signal == "Red" or tcwrs >= 76:
        return "crash-risk"
    if signal == "Orange" or close < ma60:
        return "risk-off"
    if signal == "Strengthened Yellow" or close < ma20:
        return "caution"
    if signal == "Yellow" or close < ma20 * 1.01:
        return "watch"
    return "risk-on"


def _price_proxy_tail_risk(
    closes: Sequence[float], drawdown: float, one_day_return: float, two_day_return: float
) -> float:
    twenty_returns = [
        _pct_change(closes[index - 1], closes[index])
        for index in range(max(1, len(closes) - 19), len(closes))
    ]
    volatility = statistics.pstdev(twenty_returns) if len(twenty_returns) > 1 else 0.0
    return min(100.0, max(drawdown * 2.5, volatility * 18.0, abs(min(one_day_return, two_day_return)) * 9.0))


def _price_proxy_bcd(close: float, ma20: float, drawdown: float, consecutive_down_days: int) -> float:
    below_ma20_pressure = max(0.0, (ma20 - close) / ma20 * 500.0) if ma20 else 0.0
    return min(100.0, max(drawdown * 2.0, below_ma20_pressure, consecutive_down_days * 12.0))


def _month_starts_desc(as_of: date, count: int) -> Iterable[date]:
    year = as_of.year
    month = as_of.month
    for _ in range(count):
        yield date(year, month, 1)
        month -= 1
        if month == 0:
            year -= 1
            month = 12


def _field_value(values: Sequence[Any], fields: Sequence[str], name: str, fallback_index: int) -> Any:
    if fields and name in fields:
        index = fields.index(name)
        if index < len(values):
            return values[index]
    return values[fallback_index]


def _parse_twse_date(value: Any) -> date:
    text = str(value).strip()
    parts = text.replace("/", "-").split("-")
    if len(parts) == 3 and len(parts[0]) <= 3:
        return date(int(parts[0]) + 1911, int(parts[1]), int(parts[2]))
    return date.fromisoformat(text.replace("/", "-"))


def _parse_number(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text in {"", "--", "-"}:
        raise ValueError(f"cannot parse numeric TWSE value: {value!r}")
    number = float(text)
    if not math.isfinite(number):
        raise ValueError(f"non-finite TWSE numeric value: {value!r}")
    return number


def _optional_number(value: Any) -> float | None:
    try:
        return _parse_number(value)
    except (TypeError, ValueError):
        return None


def _coerce_date(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _moving_average(values: Sequence[float], window: int) -> float:
    if len(values) < window:
        raise ValueError(f"at least {window} values are required")
    return sum(values[-window:]) / window


def _pct_change(previous: float, current: float) -> float:
    if previous == 0:
        return 0.0
    return (current - previous) / previous * 100.0


def _consecutive_down_days(closes: Sequence[float]) -> int:
    count = 0
    for index in range(len(closes) - 1, 0, -1):
        if closes[index] < closes[index - 1]:
            count += 1
        else:
            break
    return count


def _consecutive_below_ma20(closes: Sequence[float]) -> int:
    count = 0
    for end in range(len(closes), 19, -1):
        ma20 = _moving_average(closes[:end], 20)
        if closes[end - 1] < ma20:
            count += 1
        else:
            break
    return count


def _iso_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
