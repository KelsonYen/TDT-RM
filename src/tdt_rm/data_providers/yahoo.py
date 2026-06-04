"""Yahoo Finance/Stooq market-data fallback providers."""

from __future__ import annotations

import csv
import io
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Mapping

from tdt_rm.market_data import MarketPriceBar, derive_price_features

from .base import DailyDataProvider, ProviderContext, ProviderResult
from .normalizers import normalize_public_row


@dataclass(frozen=True)
class YahooProvider(DailyDataProvider):
    name: str = "YAHOO_FINANCE"
    datasets: tuple[str, ...] = ("price", "fx", "leadership")

    def fetch(self, dataset: str, context: ProviderContext) -> ProviderResult:
        start = context.trade_date - timedelta(days=context.lookback_days)
        if dataset == "price":
            bars = _yahoo_bars("^TWII", start, context.trade_date, context.timeout)
            row = _price_row(bars, context.trade_date)
        elif dataset == "fx":
            bars = _yahoo_bars("USDTWD=X", start, context.trade_date, context.timeout)
            row = _fx_row(bars, context.trade_date)
        elif dataset == "leadership":
            row = _leadership_row(context, start)
        else:
            raise ValueError(f"Yahoo provider does not support {dataset}")
        provider_source = f"{self.name}:{dataset}"
        return ProviderResult(dataset, provider_source, provider_source, normalize_public_row(dataset, row, trade_date=context.trade_date, provider_source=provider_source))


@dataclass(frozen=True)
class StooqProvider(DailyDataProvider):
    name: str = "STOOQ"
    datasets: tuple[str, ...] = ("price",)

    def fetch(self, dataset: str, context: ProviderContext) -> ProviderResult:
        if dataset != "price":
            raise ValueError(f"Stooq provider does not support {dataset}")
        start = context.trade_date - timedelta(days=context.lookback_days)
        bars = _stooq_bars("twii", start, context.trade_date, context.timeout)
        row = _price_row(bars, context.trade_date)
        provider_source = f"{self.name}:twii"
        return ProviderResult(dataset, provider_source, provider_source, normalize_public_row(dataset, row, trade_date=context.trade_date, provider_source=provider_source))


def _price_row(bars: list[MarketPriceBar], trade_date: date) -> dict[str, Any]:
    bars = [bar for bar in sorted(bars, key=lambda item: item.observed_at) if bar.observed_at <= trade_date]
    if len(bars) < 60:
        raise RuntimeError(f"need at least 60 price bars; got {len(bars)}")
    features = derive_price_features(tuple(bars))
    features["date"] = trade_date.isoformat()
    features["close_below_ma20_consecutive_days"] = _close_below_ma20_consecutive_days(bars)
    features["index_5d_return_pct"] = _pct_change(bars[-1].close, bars[-6].close) if len(bars) >= 6 else 0.0
    features["previous_ma60"] = sum(bar.close for bar in bars[-61:-1]) / 60 if len(bars) >= 61 else features["ma60"]
    features.setdefault("return_60d_pct", _pct_change(bars[-1].close, bars[-60].close))
    return features


def _fx_row(bars: list[MarketPriceBar], trade_date: date) -> dict[str, Any]:
    bars = [bar for bar in sorted(bars, key=lambda item: item.observed_at) if bar.observed_at <= trade_date]
    if len(bars) < 6:
        raise RuntimeError(f"need at least 6 USD/TWD observations; got {len(bars)}")
    latest = bars[-1].close
    chg3 = _pct_change(latest, bars[-4].close)
    chg5 = _pct_change(latest, bars[-6].close)
    return {"date": trade_date.isoformat(), "usd_twd": latest, "usd_twd_3d_change_pct": chg3, "usd_twd_5d_change_pct": chg5}


def _leadership_row(context: ProviderContext, start: date) -> dict[str, Any]:
    symbols = context.main7_symbols
    if not symbols:
        raise RuntimeError("main-7 symbols are required for Yahoo leadership")
    below20: list[str] = []
    below60: list[str] = []
    for symbol in symbols:
        yahoo_symbol = symbol if "." in symbol or symbol.startswith("^") else f"{symbol}.TW"
        bars = _yahoo_bars(yahoo_symbol, start, context.trade_date, context.timeout)
        bars = [bar for bar in sorted(bars, key=lambda item: item.observed_at) if bar.observed_at <= context.trade_date]
        if len(bars) < 60:
            raise RuntimeError(f"{yahoo_symbol} has only {len(bars)} bars")
        closes = [bar.close for bar in bars]
        if closes[-1] < sum(closes[-20:]) / 20:
            below20.append(symbol)
        if closes[-1] < sum(closes[-60:]) / 60:
            below60.append(symbol)
    return {
        "date": context.trade_date.isoformat(),
        "count_main_7_below_ma20": len(below20),
        "count_main_7_below_ma60": len(below60),
        "majority_main_7_assets_above_ma20": len(below20) < (len(symbols) / 2),
        "main_7_symbols": ",".join(symbols),
        "main_7_below_ma20_symbols": ",".join(below20),
        "mhs": round(100.0 * (len(symbols) - len(below20)) / len(symbols), 4),
    }


def _yahoo_bars(symbol: str, start: date, end: date, timeout: int) -> list[MarketPriceBar]:
    period1 = int(datetime.combine(start, time.min, tzinfo=timezone.utc).timestamp())
    period2 = int(datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc).timestamp())
    encoded = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?period1={period1}&period2={period2}&interval=1d&events=history"
    payload = _get_json(url, timeout)
    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not isinstance(result, Mapping):
        raise RuntimeError(f"Yahoo returned no chart result for {symbol}")
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    volumes = quote.get("volume") or []
    bars: list[MarketPriceBar] = []
    for idx, stamp in enumerate(timestamps):
        close = closes[idx] if idx < len(closes) else None
        if close is None:
            continue
        observed = datetime.fromtimestamp(int(stamp), tz=timezone.utc).date()
        bars.append(MarketPriceBar(observed_at=observed, close=float(close), turnover_amount=float(volumes[idx] if idx < len(volumes) and volumes[idx] is not None else 0.0), open=_optional(opens, idx), high=_optional(highs, idx), low=_optional(lows, idx), volume=_optional(volumes, idx)))
    return bars


def _stooq_bars(symbol: str, start: date, end: date, timeout: int) -> list[MarketPriceBar]:
    url = f"https://stooq.com/q/d/l/?s={urllib.parse.quote(symbol)}&i=d&d1={start:%Y%m%d}&d2={end:%Y%m%d}"
    text = _get_text(url, timeout)
    bars: list[MarketPriceBar] = []
    for row in csv.DictReader(io.StringIO(text)):
        close = row.get("Close")
        if not close or close == "0":
            continue
        bars.append(MarketPriceBar(observed_at=date.fromisoformat(row["Date"]), close=float(close), turnover_amount=float(row.get("Volume") or 0), open=float(row["Open"]) if row.get("Open") else None, high=float(row["High"]) if row.get("High") else None, low=float(row["Low"]) if row.get("Low") else None))
    return bars


def _get_json(url: str, timeout: int) -> Mapping[str, Any]:
    return json.loads(_get_text(url, timeout))


def _get_text(url: str, timeout: int) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (TDT-RM multi-provider)"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS provider URLs.
        return response.read().decode("utf-8-sig")


def _optional(values: Iterable[Any], idx: int) -> float | None:
    seq = list(values)
    if idx >= len(seq) or seq[idx] is None:
        return None
    return float(seq[idx])


def _close_below_ma20_consecutive_days(bars: list[MarketPriceBar]) -> int:
    closes = [bar.close for bar in bars]
    count = 0
    for index in range(len(closes), 19, -1):
        ma20 = sum(closes[index - 20:index]) / 20
        if closes[index - 1] < ma20:
            count += 1
        else:
            break
    return count


def _pct_change(current: float, previous: float) -> float:
    return 0.0 if previous == 0 else (current / previous - 1.0) * 100.0
