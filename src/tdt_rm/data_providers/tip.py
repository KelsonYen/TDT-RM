"""Taiwan Index Plus market-data fallback providers.

Taiwan Index Plus is kept ahead of vendor feeds in the production fallback
order because it is an official Taiwan index-data channel.  The current adapter
only supports endpoints supplied through ``config/public_data_sources.json``;
when no TIP source is configured it fails closed and the caller advances to the
next provider without fabricating data.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping

from tdt_rm.market_data import MarketPriceBar, derive_price_features
from tdt_rm.public_data_fetchers import load_source_config

from .base import DailyDataProvider, ProviderContext, ProviderResult
from .normalizers import normalize_public_row
from .yahoo import _close_below_ma20_consecutive_days, _pct_change


@dataclass(frozen=True)
class TaiwanIndexPlusProvider(DailyDataProvider):
    """Official Taiwan Index Plus provider, configured but never guessed."""

    source_config: str | None = None
    name: str = "TAIWAN_INDEX_PLUS_OFFICIAL"
    datasets: tuple[str, ...] = ("price",)

    def fetch(self, dataset: str, context: ProviderContext) -> ProviderResult:
        if dataset != "price":
            raise ValueError(f"Taiwan Index Plus provider does not support {dataset}")
        config = _tip_source_config(self.source_config)
        bars = _tip_price_bars(config, context)
        row = _price_row(bars, context.trade_date)
        source_id = str(config.get("source_id") or "taiwan_index_plus_price")
        provider_source = f"{self.name}:{source_id}"
        return ProviderResult(dataset, provider_source, source_id, normalize_public_row(dataset, row, trade_date=context.trade_date, provider_source=provider_source), {"source_configured": True})


def _tip_source_config(source_config: str | None) -> Mapping[str, Any]:
    payload = load_source_config(source_config)
    for item in payload.get("sources", []) if isinstance(payload.get("sources"), list) else []:
        if not isinstance(item, Mapping) or item.get("enabled", True) is False:
            continue
        source_id = str(item.get("source_id") or "").lower()
        adapter = str(item.get("adapter") or "").lower()
        source_type = str(item.get("source_type") or "").lower()
        if "taiwan_index_plus" in {source_id, adapter, source_type} or source_id.startswith("tip_") or adapter.startswith("tip_"):
            return item
    raise RuntimeError("missing enabled Taiwan Index Plus price source config")


def _tip_price_bars(config: Mapping[str, Any], context: ProviderContext) -> list[MarketPriceBar]:
    if isinstance(config.get("fixture_path"), str) and config.get("fixture_path"):
        from pathlib import Path

        payload = json.loads(Path(str(config["fixture_path"])).read_text(encoding="utf-8-sig"))
    else:
        template = str(config.get("endpoint_url_template") or "")
        if not template:
            raise RuntimeError("Taiwan Index Plus source requires endpoint_url_template or fixture_path")
        start = context.trade_date - timedelta(days=context.lookback_days)
        url = template.format(yyyymmdd=f"{context.trade_date:%Y%m%d}", start_yyyymmdd=f"{start:%Y%m%d}", end_yyyymmdd=f"{context.trade_date:%Y%m%d}")
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (TDT-RM multi-provider)"})
        with urllib.request.urlopen(request, timeout=context.timeout) as response:  # noqa: S310 - configured HTTPS provider URL.
            payload = json.loads(response.read().decode("utf-8-sig"))
    rows = _rows_at_path(payload, str(config.get("rows_path") or "data"))
    bars = [_tip_bar(row) for row in rows]
    return [bar for bar in bars if bar is not None]


def _rows_at_path(payload: Any, path: str) -> list[Any]:
    current = payload
    for part in [item for item in path.split(".") if item]:
        if isinstance(current, Mapping):
            current = current.get(part, [])
        else:
            return []
    return list(current) if isinstance(current, list) else []


def _tip_bar(row: Any) -> MarketPriceBar | None:
    if isinstance(row, Mapping):
        observed = row.get("date") or row.get("trade_date") or row.get("日期")
        close = row.get("close") or row.get("taiex_close") or row.get("收盤指數") or row.get("收盤價")
        turnover = row.get("turnover_amount") or row.get("turnover") or row.get("成交金額") or 0
    elif isinstance(row, list) and len(row) >= 2:
        observed, close = row[0], row[1]
        turnover = row[2] if len(row) > 2 else 0
    else:
        return None
    if not observed or close in {None, ""}:
        return None
    return MarketPriceBar(observed_at=_parse_date(str(observed)), close=_number(close), turnover_amount=_number(turnover))


def _parse_date(value: str):
    from datetime import date

    cleaned = value.strip().replace("/", "-")
    if cleaned.isdigit() and len(cleaned) == 8:
        return date(int(cleaned[:4]), int(cleaned[4:6]), int(cleaned[6:8]))
    parts = cleaned.split("-")
    if len(parts) == 3 and len(parts[0]) <= 3:
        return date(int(parts[0]) + 1911, int(parts[1]), int(parts[2]))
    return date.fromisoformat(cleaned[:10])


def _number(value: Any) -> float:
    return float(str(value).replace(",", ""))


def _price_row(bars: list[MarketPriceBar], trade_date):
    bars = [bar for bar in sorted(bars, key=lambda item: item.observed_at) if bar.observed_at <= trade_date]
    if len(bars) < 60:
        raise RuntimeError(f"need at least 60 Taiwan Index Plus price bars; got {len(bars)}")
    features = derive_price_features(tuple(bars))
    features["date"] = trade_date.isoformat()
    features["close_below_ma20_consecutive_days"] = _close_below_ma20_consecutive_days(bars)
    features["index_5d_return_pct"] = _pct_change(bars[-1].close, bars[-6].close) if len(bars) >= 6 else 0.0
    features["previous_ma60"] = sum(bar.close for bar in bars[-61:-1]) / 60 if len(bars) >= 61 else features["ma60"]
    features.setdefault("return_60d_pct", _pct_change(bars[-1].close, bars[-60].close))
    return features
