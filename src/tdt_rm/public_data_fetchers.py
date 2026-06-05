"""Public data fetchers for generating daily provider CSV inputs.

This module is intentionally limited to public-data acquisition and provider CSV
normalization. It does not score TDT-RM signals and does not change TCWRS,
ETI-5, Crash Probability, Bear Trend Filter, CAL, or decision-matrix logic.
"""

from __future__ import annotations

import csv
import html
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import hashlib
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .market_data import MarketPriceBar, derive_price_features

_REQUIRED_PROVIDER_CATEGORIES = {"price"}
_PRODUCTION_REQUIRED_PROVIDER_CATEGORIES = ("price", "foreign_flow", "fx", "breadth", "futures", "options", "leadership", "margin")
_DEFAULT_OPTIONAL_CATEGORIES = ("foreign_flow", "fx", "breadth", "futures", "options", "leadership", "margin", "scores")
_PROVIDER_CSV_NAMES = {
    "price": "price.csv",
    "foreign_flow": "foreign_flow.csv",
    "fx": "fx.csv",
    "breadth": "breadth.csv",
    "leadership": "leadership.csv",
    "margin": "margin.csv",
    "scores": "scores.csv",
    "futures": "futures.csv",
    "options": "options.csv",
}
_PRODUCTION_PRICE_FIELDS = ("trade_date", "provider_source", "source_type", "close", "ma5", "ma20", "ma60", "ma20_slope", "one_day_return_pct", "two_day_return_pct", "close_below_ma20_consecutive_days", "index_5d_return_pct", "return_60d_pct", "previous_ma60", "turnover_amount")
_REQUIRED_PRODUCTION_PRICE_VALUES = tuple(field for field in _PRODUCTION_PRICE_FIELDS if field not in {"trade_date", "provider_source", "source_type"})
_PROVIDER_FIELDS = {
    "price": _PRODUCTION_PRICE_FIELDS,
    "foreign_flow": ("date", "foreign_spot_net_buy", "foreign_spot_net_sell", "foreign_spot_net_sell_consecutive_days", "foreign_large_sell", "foreign_spot_large_sell", "futures_hedging_increases", "futures_hedging_significant"),
    "fx": ("date", "usd_twd", "usd_twd_3d_change_pct", "usd_twd_5d_change_pct", "twd_appreciates", "twd_stable", "twd_depreciates_significantly"),
    "breadth": ("date", "advancing_issues", "declining_issues", "index_down", "declining_issues_significantly_expand", "declining_issues_significantly_gt_advancing", "declining_gt_advancing_consecutive_days", "breadth_weakens_for_2_days"),
    "leadership": ("date", "count_main_7_below_ma20", "count_main_7_below_ma60", "majority_main_7_assets_above_ma20", "main_7_symbols", "main_7_below_ma20_symbols"),
    "margin": ("date", "margin_balance_5d_flat_or_down", "hot_stock_margin_fast_increase", "margin_balance_5d_increases", "index_5d_return_pct", "margin_balance_5d_decline_pct", "margin_not_retreating"),
    "scores": ("date", "tail_risk", "bcd", "mhs", "score_status", "score_notes"),
    "futures": ("date", "txf_close", "txf_settlement", "txf_volume", "txf_open_interest", "txf_basis", "futures_source_contract"),
    "options": ("date", "txo_put_call_ratio", "txo_put_volume", "txo_call_volume", "taifex_vix", "options_source_contract"),
}


@dataclass(frozen=True)
class PublicDataFetchIssue:
    """One warning/error found while fetching or normalizing public data."""

    severity: str
    code: str
    message: str
    source_id: str | None = None
    provider_category: str | None = None
    field: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "source_id": self.source_id,
            "provider_category": self.provider_category,
            "field": self.field,
        }


@dataclass(frozen=True)
class PublicDataFetchContext:
    """Runtime context shared with all public data source adapters."""

    as_of: date
    source_config: Mapping[str, Any] = field(default_factory=dict)
    main7_symbols: tuple[str, ...] = ()
    timeout_seconds: float = 20.0
    user_agent: str = "TDT-RM public daily fetcher/0.1 (+https://www.twse.com.tw/)"
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    offline: bool = False
    fail_fast: bool = False
    cache_dir: str | Path | None = None
    cache_mode: str = "off"


@dataclass(frozen=True)
class PublicDataFetchResult:
    """Normalized result emitted by one public data source."""

    source_id: str
    source_name: str
    provider_category: str
    status: str
    rows: tuple[Mapping[str, Any], ...] = ()
    canonical_fields: Mapping[str, Any] = field(default_factory=dict)
    raw_metadata: Mapping[str, Any] = field(default_factory=dict)
    issues: tuple[PublicDataFetchIssue, ...] = ()
    retrieved_at: str | None = None

    @property
    def success(self) -> bool:
        return self.status == "success" and (bool(self.rows) or bool(self.canonical_fields))

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "provider_category": self.provider_category,
            "status": self.status,
            "row_count": len(self.rows),
            "canonical_fields": dict(self.canonical_fields),
            "raw_metadata": dict(self.raw_metadata),
            "issues": [issue.as_dict() for issue in self.issues],
            "retrieved_at": self.retrieved_at,
        }


class PublicDataSource(Protocol):
    """Protocol implemented by public daily source adapters."""

    source_id: str
    source_name: str
    provider_category: str

    def fetch(self, context: PublicDataFetchContext) -> PublicDataFetchResult:
        """Fetch and normalize public data for ``context.as_of``."""


@dataclass(frozen=True)
class ProviderCsvWriteResult:
    """Artifacts written by :func:`write_provider_csvs`."""

    output_dir: str
    provider_csv_paths: Mapping[str, str] = field(default_factory=dict)
    provider_field_map_path: str | None = None
    fetch_manifest_path: str | None = None
    provider_health_path: str | None = None
    data_status: str = "unavailable"
    issues: tuple[PublicDataFetchIssue, ...] = ()
    manifest: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "output_dir": self.output_dir,
            "provider_csv_paths": dict(self.provider_csv_paths),
            "provider_field_map_path": self.provider_field_map_path,
            "fetch_manifest_path": self.fetch_manifest_path,
            "provider_health_path": self.provider_health_path,
            "data_status": self.data_status,
            "issues": [issue.as_dict() for issue in self.issues],
            "manifest": dict(self.manifest),
        }


@dataclass
class PublicDataFetcherRegistry:
    """Registry of configured public data source adapters."""

    sources: list[PublicDataSource] = field(default_factory=list)

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | str | Path | None = None) -> "PublicDataFetcherRegistry":
        payload = load_source_config(config)
        sources: list[PublicDataSource] = []
        for item in payload.get("sources", []) if isinstance(payload.get("sources", []), list) else []:
            if not isinstance(item, Mapping) or item.get("enabled", True) is False:
                continue
            if _is_finmind_source_config(item) and not _finmind_live_allowed():
                continue
            adapter = str(item.get("adapter") or item.get("provider_category") or "generic_json")
            source_type = str(item.get("source_type") or "").lower()
            if source_type in {"local_csv_fallback", "local_json_fallback"}:
                sources.append(LocalPriceFallbackSource(item))
            elif adapter == "twse_fmtqik_price":
                sources.append(TWSEFMTQIKPriceSource(item))
            elif adapter == "twse_t86_foreign_flow":
                sources.append(TWSET86ForeignFlowSource(item))
            elif adapter == "taifex_daily_fx":
                sources.append(TAIFEXDailyFXSource(item))
            elif adapter == "cbc_daily_fx":
                sources.append(CBCDailyFXSource(item))
            elif adapter == "twse_mi_index_breadth":
                sources.append(TWSEMarketBreadthSource(item))
            elif adapter == "twse_margin":
                sources.append(TWSEMarginSource(item))
            elif adapter == "taifex_txf_futures":
                sources.append(TAIFEXTXFFuturesSource(item))
            elif adapter == "taifex_txo_options":
                sources.append(TAIFEXTXOOptionsSource(item))
            elif adapter == "twse_main7_leadership" or adapter == "leadership_main7":
                sources.append(TWSEMain7LeadershipSource(item) if adapter == "twse_main7_leadership" else LeadershipMain7Source(item))
            elif adapter == "twse_taiex_price" or source_type == "twse_json":
                sources.append(TWSETAIEXPriceSource(item))
            else:
                sources.append(GenericJsonPublicDataSource(item))
        return cls(sources)

    def fetch_all(self, context: PublicDataFetchContext) -> tuple[PublicDataFetchResult, ...]:
        """Fetch configured sources by provider category with priority fallback.

        Sources are grouped by provider category and ordered by ``fallback_order``
        (or legacy ``priority``). Live/network sources are skipped in offline mode.
        For each category the registry stops after the first successful enabled
        source; required categories therefore get fallback behavior without
        fabricating missing data.
        """

        results: list[PublicDataFetchResult] = []
        by_category: dict[str, list[PublicDataSource]] = {}
        for source in self.sources:
            if context.offline and not _is_local_fallback_source(source) and not _cache_read_enabled(context):
                continue
            by_category.setdefault(source.provider_category, []).append(source)

        for category in sorted(by_category, key=lambda item: (item not in _REQUIRED_PROVIDER_CATEGORIES, item)):
            category_sources = sorted(by_category[category], key=_source_fallback_order)
            for source in category_sources:
                started = time.monotonic()
                cached = _load_cached_result(source, context)
                if cached is not None:
                    result = cached
                elif _cache_read_only(context):
                    result = _result(
                        source,
                        "unavailable",
                        (_issue(source, "warning", "cache_miss", f"no cached provider result for {context.as_of.isoformat()}"),),
                        retrieved_at=context.retrieved_at.isoformat(),
                        metadata={"cache": {"mode": context.cache_mode, "hit": False}},
                    )
                else:
                    result = source.fetch(context)
                    _write_cached_result(source, context, result)
                duration = time.monotonic() - started
                result = replace(result, raw_metadata={**dict(result.raw_metadata), "fetch_duration_seconds": round(duration, 6)})
                results.append(result)
                if result.success:
                    break
                if context.fail_fast:
                    break
        return tuple(results)

    def source_ids(self) -> tuple[str, ...]:
        return tuple(source.source_id for source in self.sources)



def _is_finmind_source_config(config: Mapping[str, Any]) -> bool:
    haystack = " ".join(
        str(config.get(key) or "")
        for key in ("source_id", "source_name", "adapter", "source_type", "endpoint_url_template", "url")
    ).lower()
    return "finmind" in haystack


def _finmind_live_allowed() -> bool:
    value = os.environ.get("TDT_RM_ALLOW_FINMIND_LIVE") or os.environ.get("ALLOW_FINMIND_LIVE") or ""
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _normalized_cache_mode(context: PublicDataFetchContext) -> str:
    mode = str(context.cache_mode or "off").lower().replace("-", "_")
    aliases = {"true": "read_write", "rw": "read_write", "readwrite": "read_write", "replay": "read"}
    return aliases.get(mode, mode)


def _cache_read_enabled(context: PublicDataFetchContext) -> bool:
    return bool(context.cache_dir) and _normalized_cache_mode(context) in {"read", "read_write"}


def _cache_write_enabled(context: PublicDataFetchContext) -> bool:
    return bool(context.cache_dir) and _normalized_cache_mode(context) in {"write", "read_write"}


def _cache_read_only(context: PublicDataFetchContext) -> bool:
    return bool(context.cache_dir) and _normalized_cache_mode(context) == "read"


def _cache_path(source: PublicDataSource, context: PublicDataFetchContext) -> Path:
    config = getattr(source, "config", {})
    fingerprint_payload = {
        "source_id": source.source_id,
        "provider_category": source.provider_category,
        "adapter": config.get("adapter") if isinstance(config, Mapping) else None,
        "endpoint": _render_url(config, context) if isinstance(config, Mapping) else "",
        "path": str(config.get("path") or config.get("fixture_path") or "") if isinstance(config, Mapping) else "",
    }
    fingerprint = hashlib.sha256(json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    safe_source = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in source.source_id)
    safe_category = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in source.provider_category)
    return Path(context.cache_dir or ".") / context.as_of.isoformat() / safe_category / f"{safe_source}_{fingerprint}.json"


def _load_cached_result(source: PublicDataSource, context: PublicDataFetchContext) -> PublicDataFetchResult | None:
    if not _cache_read_enabled(context):
        return None
    path = _cache_path(source, context)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    result_payload = payload.get("result") if isinstance(payload, Mapping) else None
    if not isinstance(result_payload, Mapping):
        return None
    issues = tuple(
        PublicDataFetchIssue(
            str(item.get("severity") or "warning"),
            str(item.get("code") or "cached_issue"),
            str(item.get("message") or ""),
            str(item.get("source_id") or source.source_id),
            str(item.get("provider_category") or source.provider_category),
            str(item.get("field")) if item.get("field") is not None else None,
        )
        for item in result_payload.get("issues", ())
        if isinstance(item, Mapping)
    )
    metadata = dict(result_payload.get("raw_metadata") or {})
    metadata["cache"] = {"mode": context.cache_mode, "hit": True, "path": str(path), "stored_at": payload.get("stored_at")}
    return PublicDataFetchResult(
        str(result_payload.get("source_id") or source.source_id),
        str(result_payload.get("source_name") or source.source_name),
        str(result_payload.get("provider_category") or source.provider_category),
        str(result_payload.get("status") or "unavailable"),
        tuple(item for item in result_payload.get("rows", ()) if isinstance(item, Mapping)),
        dict(result_payload.get("canonical_fields") or {}),
        metadata,
        issues,
        str(result_payload.get("retrieved_at")) if result_payload.get("retrieved_at") is not None else None,
    )


def _write_cached_result(source: PublicDataSource, context: PublicDataFetchContext, result: PublicDataFetchResult) -> None:
    if not _cache_write_enabled(context) or not result.success:
        return
    path = _cache_path(source, context)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cache_version": 1,
        "stored_at": datetime.now(UTC).isoformat(),
        "as_of": context.as_of.isoformat(),
        "source_id": source.source_id,
        "provider_category": source.provider_category,
        "result": {
            "source_id": result.source_id,
            "source_name": result.source_name,
            "provider_category": result.provider_category,
            "status": result.status,
            "rows": [dict(row) for row in result.rows],
            "canonical_fields": dict(result.canonical_fields),
            "raw_metadata": dict(result.raw_metadata),
            "issues": [issue.as_dict() for issue in result.issues],
            "retrieved_at": result.retrieved_at,
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def _source_fallback_order(source: PublicDataSource) -> tuple[int, str]:
    config = getattr(source, "config", {})
    order = config.get("fallback_order", config.get("priority", 100)) if isinstance(config, Mapping) else 100
    try:
        order_int = int(order)
    except (TypeError, ValueError):
        order_int = 100
    return (order_int, source.source_id)


def _is_local_fallback_source(source: PublicDataSource) -> bool:
    config = getattr(source, "config", {})
    source_type = str(config.get("source_type") or "") if isinstance(config, Mapping) else ""
    return source_type in {"local_csv_fallback", "local_json_fallback"} or isinstance(source, LocalPriceFallbackSource)


@dataclass(frozen=True)
class GenericJsonPublicDataSource:
    """Configurable JSON/file source for optional provider categories."""

    config: Mapping[str, Any]

    @property
    def source_id(self) -> str:
        return str(self.config.get("source_id") or "public_json_source")

    @property
    def source_name(self) -> str:
        return str(self.config.get("source_name") or self.source_id)

    @property
    def provider_category(self) -> str:
        return str(self.config.get("provider_category") or "unknown")

    def fetch(self, context: PublicDataFetchContext) -> PublicDataFetchResult:
        retrieved_at = context.retrieved_at.isoformat()
        try:
            payload = _fetch_json_payload(self.config, context)
            row = _extract_row(payload, self.config, context.as_of)
            if row is None:
                return _result(self, "unavailable", ( _issue(self, "warning", "row_missing", f"no row found for {context.as_of.isoformat()}"),), retrieved_at=retrieved_at)
            mapped = _map_fields(row, self.config.get("field_mapping") or self.config.get("field_extraction_mapping") or {})
            missing = tuple(str(field) for field in self.config.get("required_fields", ()) if _missing(mapped.get(str(field))))
            if missing:
                return _result(self, "missing_fields", tuple(_issue(self, "warning", "missing_field", f"missing required field {field}", field=field) for field in missing), retrieved_at=retrieved_at)
            if _is_stale(mapped, self.config, context.as_of):
                return _result(self, "stale", (_issue(self, "warning", "stale_data", f"source data is stale for {context.as_of.isoformat()}"),), retrieved_at=retrieved_at, canonical=mapped)
            normalized = _normalize_provider_row(self.provider_category, mapped, context.as_of)
            return _result(self, "success", retrieved_at=retrieved_at, rows=(normalized,), canonical=normalized, metadata={"endpoint": _render_url(self.config, context)})
        except Exception as exc:  # noqa: BLE001 - source failures are recorded, not raised.
            return _result(self, "failed", (_issue(self, "error", "fetch_failed", str(exc)),), retrieved_at=retrieved_at, metadata={"exception_class": exc.__class__.__name__, "exception_message": str(exc)})


@dataclass(frozen=True)
class TWSETAIEXPriceSource:
    """Official TWSE TAIEX OHLC source using MI_5MINS_HIST JSON."""

    config: Mapping[str, Any]

    @property
    def source_id(self) -> str:
        return str(self.config.get("source_id") or "twse_taiex_price")

    @property
    def source_name(self) -> str:
        return str(self.config.get("source_name") or "TWSE TAIEX MI_5MINS_HIST")

    @property
    def provider_category(self) -> str:
        return "price"

    def fetch(self, context: PublicDataFetchContext) -> PublicDataFetchResult:
        retrieved_at = context.retrieved_at.isoformat()
        try:
            payload = _fetch_json_payload(self.config, context)
            bars = _parse_price_bars(payload, context.as_of)
            if len(bars) < max(61, int(self.config.get("min_bars", 1))):
                # Some fixtures/configs provide a direct canonical row instead of history.
                row = _extract_row(payload, self.config, context.as_of)
                if isinstance(row, Mapping):
                    mapped = _map_fields(row, self.config.get("field_mapping") or self.config.get("field_extraction_mapping") or {})
                    normalized = _normalize_provider_row("price", mapped, context.as_of)
                    if _has_price_minimum(normalized):
                        return _result(self, "success", retrieved_at=retrieved_at, rows=(normalized,), canonical=normalized, metadata={"endpoint": _render_url(self.config, context), "mode": "canonical_row"})
                return _result(self, "failed", (_issue(self, "error", "insufficient_price_history", f"price source returned {len(bars)} bars; cannot derive required price fields"),), retrieved_at=retrieved_at)
            bars = tuple(sorted(bars, key=lambda item: item.observed_at))
            features = _augment_price_features(derive_price_features(bars), bars)
            normalized = _normalize_provider_row("price", features, context.as_of)
            normalized["date"] = context.as_of.isoformat()
            return _result(self, "success", retrieved_at=retrieved_at, rows=(normalized,), canonical=normalized, metadata={"endpoint": _render_url(self.config, context), "bar_count": len(bars), "mode": "price_history"})
        except Exception as exc:  # noqa: BLE001
            return _result(self, "failed", (_issue(self, "error", "fetch_failed", str(exc)),), retrieved_at=retrieved_at, metadata={"exception_class": exc.__class__.__name__, "exception_message": str(exc)})


def _augment_price_features(features: Mapping[str, Any], bars: Sequence[MarketPriceBar]) -> dict[str, Any]:
    """Add strict production price fields derived only from observed bars."""

    ordered = tuple(sorted(bars, key=lambda item: item.observed_at))
    if len(ordered) < 61:
        raise ValueError("strict price production fields require at least 61 trading-day bars")
    output = dict(features)
    closes = [float(bar.close) for bar in ordered]
    output["close_below_ma20_consecutive_days"] = _close_below_ma20_consecutive_days(ordered)
    output["index_5d_return_pct"] = _pct_change(closes[-6], closes[-1])
    output["return_60d_pct"] = _pct_change(closes[-61], closes[-1])
    output["previous_ma60"] = sum(closes[-61:-1]) / 60
    return output


def _close_below_ma20_consecutive_days(bars: Sequence[MarketPriceBar]) -> int:
    closes = [float(bar.close) for bar in bars]
    count = 0
    for index in range(len(closes), 19, -1):
        ma20 = sum(closes[index - 20:index]) / 20
        if closes[index - 1] < ma20:
            count += 1
        else:
            break
    return count


def _pct_change(previous: float, current: float) -> float:
    return 0.0 if previous == 0 else (current / previous - 1.0) * 100.0


@dataclass(frozen=True)
class LocalPriceFallbackSource:
    """User-supplied local price fallback file source.

    Local fallback files are treated as externally supplied data, not generated
    market data. They must contain canonical price fields and pass the same
    as-of/freshness checks before ``price.csv`` is written.
    """

    config: Mapping[str, Any]

    @property
    def source_id(self) -> str:
        return str(self.config.get("source_id") or "local_price_fallback")

    @property
    def source_name(self) -> str:
        return str(self.config.get("source_name") or self.source_id)

    @property
    def provider_category(self) -> str:
        return "price"

    def fetch(self, context: PublicDataFetchContext) -> PublicDataFetchResult:
        retrieved_at = context.retrieved_at.isoformat()
        try:
            source_type = str(self.config.get("source_type") or "local_csv_fallback")
            path = _local_fallback_path(self.config)
            if not path:
                return _result(
                    self,
                    "unavailable",
                    (_issue(self, "warning", "local_fallback_missing", "local price fallback path is not configured"),),
                    retrieved_at=retrieved_at,
                    metadata={"source_type": source_type, "local_fallback": True},
                )
            fallback_path = Path(path)
            if not fallback_path.exists():
                return _result(
                    self,
                    "failed",
                    (_issue(self, "error", "local_fallback_not_found", f"local price fallback file not found: {fallback_path}"),),
                    retrieved_at=retrieved_at,
                    metadata={"source_type": source_type, "local_fallback": True, "path": str(fallback_path)},
                )
            rows = _read_local_fallback_rows(fallback_path, source_type, self.config)
            row = _select_local_fallback_row(rows, self.config, context.as_of)
            if row is None:
                return _result(
                    self,
                    "unavailable",
                    (_issue(self, "warning", "row_missing", f"local fallback has no row for {context.as_of.isoformat()}"),),
                    retrieved_at=retrieved_at,
                    metadata={"source_type": source_type, "local_fallback": True, "path": str(fallback_path)},
                )
            mapped = _map_fields(row, self.config.get("field_mapping") or self.config.get("field_extraction_mapping") or {})
            normalized = _normalize_provider_row("price", mapped, context.as_of)
            if _local_price_is_stale(normalized, self.config, context.as_of):
                return _result(
                    self,
                    "stale",
                    (_issue(self, "error", "stale_data", f"local price fallback is stale for {context.as_of.isoformat()}"),),
                    retrieved_at=retrieved_at,
                    canonical=normalized,
                    metadata={"source_type": source_type, "local_fallback": True, "path": str(fallback_path)},
                )
            missing = _missing_production_price_fields(normalized)
            if missing:
                return _result(
                    self,
                    "missing_fields",
                    tuple(_issue(self, "error", "missing_field", f"local price fallback missing required field {field}", field=field) for field in missing),
                    retrieved_at=retrieved_at,
                    canonical=normalized,
                    metadata={"source_type": source_type, "local_fallback": True, "path": str(fallback_path)},
                )
            normalized["date"] = context.as_of.isoformat()
            return _result(
                self,
                "success",
                retrieved_at=retrieved_at,
                rows=(normalized,),
                canonical=normalized,
                metadata={"source_type": source_type, "local_fallback": True, "path": str(fallback_path)},
            )
        except Exception as exc:  # noqa: BLE001
            return _result(self, "failed", (_issue(self, "error", "fetch_failed", str(exc)),), retrieved_at=retrieved_at, metadata={"local_fallback": True, "exception_class": exc.__class__.__name__, "exception_message": str(exc)})


@dataclass(frozen=True)
class LeadershipMain7Source:
    """Compute Main-7 leadership from configured constituent price rows when supplied."""

    config: Mapping[str, Any]

    @property
    def source_id(self) -> str:
        return str(self.config.get("source_id") or "main7_leadership")

    @property
    def source_name(self) -> str:
        return str(self.config.get("source_name") or "Main-7 leadership public source")

    @property
    def provider_category(self) -> str:
        return "leadership"

    def fetch(self, context: PublicDataFetchContext) -> PublicDataFetchResult:
        retrieved_at = context.retrieved_at.isoformat()
        try:
            payload = _fetch_json_payload(self.config, context)
            rows = _extract_rows(payload, self.config)
            symbols = tuple(context.main7_symbols or tuple(str(item) for item in self.config.get("symbols", ())))
            if not symbols:
                return _result(self, "unavailable", (_issue(self, "warning", "main7_config_missing", "main-7 symbol list is empty"),), retrieved_at=retrieved_at)
            by_symbol = {str((row.get("symbol") or row.get("code") or row.get("證券代號") or "")).strip(): row for row in rows if isinstance(row, Mapping)}
            missing_symbols = [symbol for symbol in symbols if symbol not in by_symbol]
            if missing_symbols:
                return _result(self, "missing_fields", (_issue(self, "warning", "constituents_missing", "missing main-7 constituent rows: " + ",".join(missing_symbols), field="main_7_symbols"),), retrieved_at=retrieved_at)
            below20: list[str] = []
            below60: list[str] = []
            for symbol in symbols:
                row = by_symbol[symbol]
                close = _to_float(row.get("close") or row.get("收盤價"))
                ma20 = _to_float(row.get("ma20"))
                ma60 = _to_float(row.get("ma60"))
                if close is None or ma20 is None:
                    return _result(self, "missing_fields", (_issue(self, "warning", "constituent_field_missing", f"missing close/ma20 for {symbol}", field=symbol),), retrieved_at=retrieved_at)
                if close < ma20:
                    below20.append(symbol)
                if ma60 is not None and close < ma60:
                    below60.append(symbol)
            normalized = {
                "date": context.as_of.isoformat(),
                "count_main_7_below_ma20": len(below20),
                "count_main_7_below_ma60": len(below60),
                "majority_main_7_assets_above_ma20": len(below20) < math.ceil(len(symbols) / 2),
                "main_7_symbols": ",".join(symbols),
                "main_7_below_ma20_symbols": ",".join(below20),
            }
            return _result(self, "success", retrieved_at=retrieved_at, rows=(normalized,), canonical=normalized, metadata={"endpoint": _render_url(self.config, context)})
        except Exception as exc:  # noqa: BLE001
            return _result(self, "failed", (_issue(self, "error", "fetch_failed", str(exc)),), retrieved_at=retrieved_at, metadata={"exception_class": exc.__class__.__name__, "exception_message": str(exc)})



@dataclass(frozen=True)
class TWSEFMTQIKPriceSource:
    """Official TWSE monthly market summary source for TAIEX close/turnover."""

    config: Mapping[str, Any]

    @property
    def source_id(self) -> str:
        return str(self.config.get("source_id") or "twse_fmtqik_price")

    @property
    def source_name(self) -> str:
        return str(self.config.get("source_name") or "TWSE FMTQIK market summary")

    @property
    def provider_category(self) -> str:
        return "price"

    def fetch(self, context: PublicDataFetchContext) -> PublicDataFetchResult:
        retrieved_at = context.retrieved_at.isoformat()
        try:
            payloads = _fetch_configured_payloads(self.config, context)
            bars: list[MarketPriceBar] = []
            for payload in payloads:
                bars.extend(_parse_fmtqik_price_bars(payload, context.as_of))
            bars = sorted({bar.observed_at: bar for bar in bars if bar.observed_at <= context.as_of}.values(), key=lambda item: item.observed_at)
            if len(bars) < max(61, int(self.config.get("min_bars", 61))):
                return _result(self, "failed", (_issue(self, "error", "insufficient_price_history", f"TWSE FMTQIK returned {len(bars)} usable bars; cannot derive strict price fields requiring 61+ trading days"),), retrieved_at=retrieved_at, metadata={"endpoint": _render_url(self.config, context), "bar_count": len(bars)})
            latest_date = bars[-1].observed_at
            if _date_lag_failed(latest_date, self.config, context.as_of):
                return _result(self, "stale", (_issue(self, "error", "stale_data", f"latest TWSE FMTQIK row is {latest_date.isoformat()} for as-of {context.as_of.isoformat()}"),), retrieved_at=retrieved_at, metadata={"endpoint": _render_url(self.config, context), "bar_count": len(bars)})
            features = _augment_price_features(derive_price_features(tuple(bars)), tuple(bars))
            normalized = _normalize_provider_row("price", features, context.as_of)
            normalized["date"] = context.as_of.isoformat()
            return _result(self, "success", retrieved_at=retrieved_at, rows=(normalized,), canonical=normalized, metadata={"endpoint": _render_url(self.config, context), "bar_count": len(bars), "official_source": "TWSE FMTQIK"})
        except Exception as exc:  # noqa: BLE001
            return _result(self, "failed", (_issue(self, "error", "fetch_failed", str(exc)),), retrieved_at=retrieved_at, metadata={"exception_class": exc.__class__.__name__, "exception_message": str(exc)})


@dataclass(frozen=True)
class TWSET86ForeignFlowSource:
    """Official TWSE T86 foreign investor net buy/sell parser."""

    config: Mapping[str, Any]

    @property
    def source_id(self) -> str:
        return str(self.config.get("source_id") or "twse_t86_foreign_flow")

    @property
    def source_name(self) -> str:
        return str(self.config.get("source_name") or "TWSE T86 foreign flow")

    @property
    def provider_category(self) -> str:
        return "foreign_flow"

    def fetch(self, context: PublicDataFetchContext) -> PublicDataFetchResult:
        retrieved_at = context.retrieved_at.isoformat()
        try:
            payloads = _fetch_configured_payloads(self.config, context)
            daily = [_parse_t86_foreign_flow(payload, context.as_of - timedelta(days=offset)) for offset, payload in enumerate(payloads)]
            rows = [row for row in daily if row]
            if not rows:
                return _result(self, "unavailable", (_issue(self, "warning", "row_missing", f"no TWSE T86 row for {context.as_of.isoformat()}"),), retrieved_at=retrieved_at)
            current = rows[0]
            sell_days = 0
            for row in rows:
                if bool(row.get("foreign_spot_net_sell")):
                    sell_days += 1
                else:
                    break
            current["foreign_spot_net_sell_consecutive_days"] = sell_days
            return _result(self, "success", retrieved_at=retrieved_at, rows=(current,), canonical=current, metadata={"endpoint": _render_url(self.config, context), "official_source": "TWSE T86"})
        except Exception as exc:  # noqa: BLE001
            return _result(self, "failed", (_issue(self, "error", "fetch_failed", str(exc)),), retrieved_at=retrieved_at, metadata={"exception_class": exc.__class__.__name__, "exception_message": str(exc)})


@dataclass(frozen=True)
class TAIFEXDailyFXSource:
    """Official TAIFEX daily foreign-exchange-rate parser for USD/TWD."""

    config: Mapping[str, Any]

    @property
    def source_id(self) -> str:
        return str(self.config.get("source_id") or "taifex_daily_fx")

    @property
    def source_name(self) -> str:
        return str(self.config.get("source_name") or "TAIFEX daily foreign exchange rates")

    @property
    def provider_category(self) -> str:
        return "fx"

    def fetch(self, context: PublicDataFetchContext) -> PublicDataFetchResult:
        retrieved_at = context.retrieved_at.isoformat()
        try:
            rows: list[dict[str, Any]] = []
            for payload in _fetch_configured_payloads(self.config, context):
                rows.extend(_parse_taifex_fx_rows(payload, context.as_of))
            rows = sorted({row["date"]: row for row in rows if _parse_date(row.get("date")) and _parse_date(row.get("date")) <= context.as_of}.values(), key=lambda item: str(item["date"]))
            if not rows:
                return _result(self, "unavailable", (_issue(self, "warning", "row_missing", f"no TAIFEX USD/TWD row for {context.as_of.isoformat()}"),), retrieved_at=retrieved_at)
            row = rows[-1]
            row["usd_twd_3d_change_pct"] = _pct_change_from_rows(rows, 3, "usd_twd")
            row["usd_twd_5d_change_pct"] = _pct_change_from_rows(rows, 5, "usd_twd")
            change5 = _to_float(row.get("usd_twd_5d_change_pct")) or 0.0
            row["twd_appreciates"] = change5 < -0.5
            row["twd_stable"] = abs(change5) <= 0.5
            row["twd_depreciates_significantly"] = change5 >= 1.0
            return _result(self, "success", retrieved_at=retrieved_at, rows=(row,), canonical=row, metadata={"endpoint": _render_url(self.config, context), "official_source": "TAIFEX DailyForeignExchangeRates"})
        except Exception as exc:  # noqa: BLE001
            return _result(self, "failed", (_issue(self, "error", "fetch_failed", str(exc)),), retrieved_at=retrieved_at, metadata={"exception_class": exc.__class__.__name__, "exception_message": str(exc)})


@dataclass(frozen=True)
class CBCDailyFXSource:
    """Official CBC Statistical Database parser for daily NTD/USD rates."""

    config: Mapping[str, Any]

    @property
    def source_id(self) -> str:
        return str(self.config.get("source_id") or "cbc_daily_fx")

    @property
    def source_name(self) -> str:
        return str(self.config.get("source_name") or "CBC daily NTD/USD exchange rates")

    @property
    def provider_category(self) -> str:
        return "fx"

    def fetch(self, context: PublicDataFetchContext) -> PublicDataFetchResult:
        retrieved_at = context.retrieved_at.isoformat()
        try:
            rows: list[dict[str, Any]] = []
            for payload in _fetch_configured_payloads(self.config, context):
                rows.extend(_parse_cbc_fx_rows(payload, context.as_of))
            rows = sorted({row["date"]: row for row in rows if _parse_date(row.get("date")) and _parse_date(row.get("date")) <= context.as_of}.values(), key=lambda item: str(item["date"]))
            if not rows:
                return _result(self, "unavailable", (_issue(self, "warning", "row_missing", f"no CBC USD/TWD row on or before {context.as_of.isoformat()}"),), retrieved_at=retrieved_at)
            row = rows[-1]
            row["usd_twd_3d_change_pct"] = _pct_change_from_rows(rows, 3, "usd_twd")
            row["usd_twd_5d_change_pct"] = _pct_change_from_rows(rows, 5, "usd_twd")
            change5 = _to_float(row.get("usd_twd_5d_change_pct")) or 0.0
            row["twd_appreciates"] = change5 < -0.5
            row["twd_stable"] = abs(change5) <= 0.5
            row["twd_depreciates_significantly"] = change5 >= 1.0
            return _result(self, "success", retrieved_at=retrieved_at, rows=(row,), canonical=row, metadata={"endpoint": _render_url(self.config, context), "official_source": "CBC Statistical Database BP01D01en"})
        except Exception as exc:  # noqa: BLE001
            return _result(self, "failed", (_issue(self, "error", "fetch_failed", str(exc)),), retrieved_at=retrieved_at, metadata={"exception_class": exc.__class__.__name__, "exception_message": str(exc)})


@dataclass(frozen=True)
class TWSEMarketBreadthSource:
    """Official TWSE MI_INDEX market breadth parser."""

    config: Mapping[str, Any]

    @property
    def source_id(self) -> str:
        return str(self.config.get("source_id") or "twse_mi_index_breadth")

    @property
    def source_name(self) -> str:
        return str(self.config.get("source_name") or "TWSE MI_INDEX breadth")

    @property
    def provider_category(self) -> str:
        return "breadth"

    def fetch(self, context: PublicDataFetchContext) -> PublicDataFetchResult:
        retrieved_at = context.retrieved_at.isoformat()
        try:
            rows = [_parse_twse_breadth(payload, context.as_of) for payload in _fetch_configured_payloads(self.config, context)]
            row = next((item for item in rows if item), None)
            if not row:
                return _result(self, "unavailable", (_issue(self, "warning", "row_missing", f"no TWSE breadth row for {context.as_of.isoformat()}"),), retrieved_at=retrieved_at)
            normalized = _normalize_provider_row("breadth", row, context.as_of)
            return _result(self, "success", retrieved_at=retrieved_at, rows=(normalized,), canonical=normalized, metadata={"endpoint": _render_url(self.config, context), "official_source": "TWSE MI_INDEX"})
        except Exception as exc:  # noqa: BLE001
            return _result(self, "failed", (_issue(self, "error", "fetch_failed", str(exc)),), retrieved_at=retrieved_at, metadata={"exception_class": exc.__class__.__name__, "exception_message": str(exc)})


@dataclass(frozen=True)
class TWSEMarginSource:
    """Official TWSE MI_MARGN margin-balance parser."""

    config: Mapping[str, Any]

    @property
    def source_id(self) -> str:
        return str(self.config.get("source_id") or "twse_margin")

    @property
    def source_name(self) -> str:
        return str(self.config.get("source_name") or "TWSE MI_MARGN margin balance")

    @property
    def provider_category(self) -> str:
        return "margin"

    def fetch(self, context: PublicDataFetchContext) -> PublicDataFetchResult:
        retrieved_at = context.retrieved_at.isoformat()
        try:
            lookback_days = int(self.config.get("lookback_days", 14) or 14)
            points_by_day: dict[date, float] = {}
            for offset in range(lookback_days + 1):
                observed = context.as_of - timedelta(days=offset)
                payload = _fetch_any_payload(self.config, replace(context, as_of=observed))
                balance = _parse_twse_margin_balance(payload)
                if balance is not None:
                    points_by_day[observed] = balance
            points = sorted((day, balance) for day, balance in points_by_day.items() if day <= context.as_of)
            if len(points) < 6 or points[-1][0] != context.as_of:
                latest = points[-1][0].isoformat() if points else "none"
                return _result(self, "unavailable", (_issue(self, "warning", "row_missing", f"TWSE MI_MARGN has {len(points)} usable observations through {latest}; need current as-of row plus 5 prior trading observations for {context.as_of.isoformat()}"),), retrieved_at=retrieved_at, metadata={"endpoint": _render_url(self.config, context), "observations": len(points), "latest_observation": latest})
            current = points[-1][1]
            previous = points[-2][1]
            prior5 = points[-6][1]
            decline_pct = ((prior5 - current) / prior5 * 100.0) if prior5 else 0.0
            row = {
                "date": context.as_of.isoformat(),
                "margin_balance_5d_flat_or_down": current <= previous,
                "hot_stock_margin_fast_increase": False,
                "margin_balance_5d_increases": current > previous,
                "index_5d_return_pct": 0.0,
                "margin_balance_5d_decline_pct": max(0.0, decline_pct),
                "margin_not_retreating": current >= prior5,
            }
            normalized = _normalize_provider_row("margin", row, context.as_of)
            return _result(self, "success", retrieved_at=retrieved_at, rows=(normalized,), canonical=normalized, metadata={"endpoint": _render_url(self.config, context), "observations": len(points), "latest_margin_balance": current, "prior_5_observation_date": points[-6][0].isoformat(), "official_source": "TWSE MI_MARGN"})
        except Exception as exc:  # noqa: BLE001
            return _result(self, "failed", (_issue(self, "error", "fetch_failed", str(exc)),), retrieved_at=retrieved_at, metadata={"exception_class": exc.__class__.__name__, "exception_message": str(exc), "endpoint": _render_url(self.config, context)})


@dataclass(frozen=True)
class TAIFEXTXFFuturesSource:
    """Official TAIFEX daily market report parser for TAIEX futures."""

    config: Mapping[str, Any]

    @property
    def source_id(self) -> str:
        return str(self.config.get("source_id") or "taifex_txf_futures")

    @property
    def source_name(self) -> str:
        return str(self.config.get("source_name") or "TAIFEX TXF futures")

    @property
    def provider_category(self) -> str:
        return "futures"

    def fetch(self, context: PublicDataFetchContext) -> PublicDataFetchResult:
        retrieved_at = context.retrieved_at.isoformat()
        try:
            row = next((parsed for payload in _fetch_configured_payloads(self.config, context) for parsed in [_parse_taifex_futures(payload, context.as_of)] if parsed), None)
            if not row:
                return _result(self, "unavailable", (_issue(self, "warning", "row_missing", f"no TAIFEX TXF row for {context.as_of.isoformat()}"),), retrieved_at=retrieved_at)
            return _result(self, "success", retrieved_at=retrieved_at, rows=(row,), canonical=row, metadata={"endpoint": _render_url(self.config, context), "official_source": "TAIFEX DailyMarketReportFut"})
        except Exception as exc:  # noqa: BLE001
            return _result(self, "failed", (_issue(self, "error", "fetch_failed", str(exc)),), retrieved_at=retrieved_at, metadata={"exception_class": exc.__class__.__name__, "exception_message": str(exc)})


@dataclass(frozen=True)
class TAIFEXTXOOptionsSource:
    """Official TAIFEX PCR and VIX parser for TAIEX options."""

    config: Mapping[str, Any]

    @property
    def source_id(self) -> str:
        return str(self.config.get("source_id") or "taifex_txo_options")

    @property
    def source_name(self) -> str:
        return str(self.config.get("source_name") or "TAIFEX TXO options PCR/VIX")

    @property
    def provider_category(self) -> str:
        return "options"

    def fetch(self, context: PublicDataFetchContext) -> PublicDataFetchResult:
        retrieved_at = context.retrieved_at.isoformat()
        row: dict[str, Any] = {"date": context.as_of.isoformat()}
        issues: list[PublicDataFetchIssue] = []
        endpoint_statuses: list[dict[str, Any]] = []
        for endpoint_config, endpoint_url in _iter_configured_endpoint_configs(self.config, context):
            try:
                payload = _fetch_any_payload(endpoint_config, context)
                parsed = _parse_taifex_options(payload, context.as_of)
                usable_fields = sorted(key for key, value in parsed.items() if key != "date" and not _missing(value))
                if usable_fields:
                    row.update(parsed)
                    endpoint_statuses.append({
                        "endpoint": endpoint_url,
                        "status": "success",
                        "usable_fields": usable_fields,
                    })
                else:
                    endpoint_statuses.append({"endpoint": endpoint_url, "status": "unavailable", "usable_fields": []})
                    issues.append(_issue(self, "warning", "endpoint_row_missing", f"no usable TAIFEX options row at {endpoint_url}"))
            except Exception as exc:  # noqa: BLE001
                endpoint_statuses.append({
                    "endpoint": endpoint_url,
                    "status": "failed",
                    "exception_class": exc.__class__.__name__,
                    "error": str(exc),
                })
                issues.append(_issue(self, "warning", "endpoint_fetch_failed", f"{endpoint_url}: {exc}"))
        has_pcr = not _missing(row.get("txo_put_call_ratio"))
        has_vix = not _missing(row.get("taifex_vix"))
        metadata = {
            "endpoint": _render_url(self.config, context),
            "endpoints": endpoint_statuses,
            "official_source": "TAIFEX PutCallRatio/TAIFEXVIX",
        }
        if not has_pcr and not has_vix:
            severity = "error" if endpoint_statuses and all(item.get("status") == "failed" for item in endpoint_statuses) else "warning"
            return _result(
                self,
                "failed" if severity == "error" else "unavailable",
                tuple(issues) + (_issue(self, severity, "row_missing", f"no TAIFEX PCR/VIX row for {context.as_of.isoformat()}"),),
                retrieved_at=retrieved_at,
                metadata=metadata,
            )
        row.setdefault("options_source_contract", "TXO")
        return _result(self, "success", tuple(issues), retrieved_at=retrieved_at, rows=(row,), canonical=row, metadata=metadata)


@dataclass(frozen=True)
class TWSEMain7LeadershipSource:
    """Official TWSE per-stock history parser for Main-7 leadership."""

    config: Mapping[str, Any]

    @property
    def source_id(self) -> str:
        return str(self.config.get("source_id") or "twse_main7_leadership")

    @property
    def source_name(self) -> str:
        return str(self.config.get("source_name") or "TWSE Main-7 leadership")

    @property
    def provider_category(self) -> str:
        return "leadership"

    def fetch(self, context: PublicDataFetchContext) -> PublicDataFetchResult:
        retrieved_at = context.retrieved_at.isoformat()
        try:
            symbols = tuple(context.main7_symbols or tuple(str(item) for item in self.config.get("symbols", ())))
            if not symbols:
                return _result(self, "unavailable", (_issue(self, "warning", "main7_config_missing", "main-7 symbol list is empty"),), retrieved_at=retrieved_at)
            below20: list[str] = []
            below60: list[str] = []
            missing: list[str] = []
            for symbol in symbols:
                bars: list[float] = []
                for payload in _fetch_symbol_payloads(self.config, context, symbol):
                    bars.extend(_parse_stock_closes(payload, context.as_of))
                closes = [value for value in bars if value is not None]
                if len(closes) < 60:
                    missing.append(symbol)
                    continue
                close = closes[-1]
                ma20 = sum(closes[-20:]) / 20
                ma60 = sum(closes[-60:]) / 60
                if close < ma20:
                    below20.append(symbol)
                if close < ma60:
                    below60.append(symbol)
            if missing:
                return _result(self, "missing_fields", (_issue(self, "warning", "constituents_missing", "missing 60-day TWSE stock history for: " + ",".join(missing), field="main_7_symbols"),), retrieved_at=retrieved_at)
            normalized = {"date": context.as_of.isoformat(), "count_main_7_below_ma20": len(below20), "count_main_7_below_ma60": len(below60), "majority_main_7_assets_above_ma20": len(below20) < math.ceil(len(symbols) / 2), "main_7_symbols": ",".join(symbols), "main_7_below_ma20_symbols": ",".join(below20)}
            return _result(self, "success", retrieved_at=retrieved_at, rows=(normalized,), canonical=normalized, metadata={"endpoint": _render_url(self.config, context), "official_source": "TWSE STOCK_DAY"})
        except Exception as exc:  # noqa: BLE001
            return _result(self, "failed", (_issue(self, "error", "fetch_failed", str(exc)),), retrieved_at=retrieved_at, metadata={"exception_class": exc.__class__.__name__, "exception_message": str(exc)})


def write_provider_csvs(fetch_results: Sequence[PublicDataFetchResult], output_dir: str | Path, as_of: date) -> ProviderCsvWriteResult:
    """Write provider CSV inputs and fetch manifests for successful public results."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    provider_paths: dict[str, str] = {}
    issues: list[PublicDataFetchIssue] = []
    for result in fetch_results:
        issues.extend(result.issues)
        if not result.success or result.provider_category not in _PROVIDER_CSV_NAMES:
            continue
        if result.provider_category == "scores" and not _scores_are_formal_or_explicit(result):
            issues.append(PublicDataFetchIssue("warning", "scores_omitted", "scores.csv omitted because no formal or explicitly provisional deterministic scores were supplied", result.source_id, "scores"))
            continue
        path = destination / _PROVIDER_CSV_NAMES[result.provider_category]
        row = dict(result.rows[0] if result.rows else result.canonical_fields)
        row.setdefault("date", as_of.isoformat())
        if result.provider_category == "price":
            production_row, validation_issues = _build_production_price_row(row, result, as_of)
            if validation_issues:
                issues.extend(validation_issues)
                continue
            _write_csv(path, _PRODUCTION_PRICE_FIELDS, production_row)
        else:
            fields = tuple(field for field in _PROVIDER_FIELDS[result.provider_category] if field in row or field == "date")
            _write_csv(path, fields, row)
        provider_paths[result.provider_category] = str(path)

    field_map_path = destination / "provider_field_map.json"
    field_map_path.write_text(json.dumps(_provider_field_map(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    provider_health = build_provider_health(fetch_results, as_of)
    health_path = destination / "provider_health.json"
    health_path.write_text(json.dumps(provider_health, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = build_fetch_manifest(fetch_results, provider_paths, as_of, provider_health=provider_health)
    data_status = str(manifest["data_status"])
    manifest_path = destination / "fetch_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ProviderCsvWriteResult(str(destination), provider_paths, str(field_map_path), str(manifest_path), str(health_path), data_status, tuple(issues), manifest)


def _build_production_price_row(row: Mapping[str, Any], result: PublicDataFetchResult, as_of: date) -> tuple[dict[str, Any], tuple[PublicDataFetchIssue, ...]]:
    output = {
        "trade_date": as_of.isoformat(),
        "provider_source": result.source_id,
        "source_type": str(result.raw_metadata.get("source_type") or ("local_csv_fallback" if result.raw_metadata.get("local_fallback") else "unknown")),
        "close": row.get("close", row.get("taiex_close")),
        "ma5": row.get("ma5", row.get("taiex_ma5")),
        "ma20": row.get("ma20", row.get("taiex_ma20")),
        "ma60": row.get("ma60", row.get("taiex_ma60")),
        "ma20_slope": row.get("ma20_slope", row.get("taiex_ma20_slope")),
        "one_day_return_pct": row.get("one_day_return_pct"),
        "two_day_return_pct": row.get("two_day_return_pct"),
        "close_below_ma20_consecutive_days": row.get("close_below_ma20_consecutive_days"),
        "index_5d_return_pct": row.get("index_5d_return_pct"),
        "return_60d_pct": row.get("return_60d_pct"),
        "previous_ma60": row.get("previous_ma60"),
        "turnover_amount": row.get("turnover_amount", row.get("taiex_turnover", row.get("turnover"))),
    }
    missing = _missing_production_price_fields(output)
    if missing:
        return output, tuple(
            PublicDataFetchIssue(
                "error",
                "missing_field",
                f"price production CSV missing required field {field}",
                result.source_id,
                "price",
                field,
            )
            for field in missing
        )
    return output, ()


def _missing_production_price_fields(row: Mapping[str, Any]) -> tuple[str, ...]:
    missing: list[str] = []
    for field in _REQUIRED_PRODUCTION_PRICE_VALUES:
        aliases = {
            "close": ("close", "taiex_close"),
            "ma5": ("ma5", "taiex_ma5"),
            "ma20": ("ma20", "taiex_ma20"),
            "ma60": ("ma60", "taiex_ma60"),
            "ma20_slope": ("ma20_slope", "taiex_ma20_slope"),
            "turnover_amount": ("turnover_amount", "taiex_turnover", "turnover"),
        }.get(field, (field,))
        if all(_missing(row.get(alias)) for alias in aliases):
            missing.append(field)
    return tuple(missing)


def build_fetch_manifest(fetch_results: Sequence[PublicDataFetchResult], provider_paths: Mapping[str, str], as_of: date, *, provider_health: Mapping[str, Any] | None = None) -> dict[str, Any]:
    attempted = [result.source_id for result in fetch_results]
    successful = [result.source_id for result in fetch_results if result.success]
    failed = [result.source_id for result in fetch_results if result.status == "failed"]
    stale = [result.source_id for result in fetch_results if result.status == "stale"]
    missing_fields = [issue.as_dict() for result in fetch_results for issue in result.issues if issue.code in {"missing_field", "constituents_missing", "constituent_field_missing"} or result.status == "missing_fields"]
    unavailable = [result.source_id for result in fetch_results if result.status in {"unavailable", "missing_fields", "stale"}]
    source_attempts = [_source_attempt_manifest(result) for result in fetch_results]
    health_payload = dict(provider_health or build_provider_health(fetch_results, as_of))
    price_available = "price" in provider_paths
    optional_categories = sorted(set(_DEFAULT_OPTIONAL_CATEGORIES) - set(provider_paths))
    missing_production_csvs = [category for category in _PRODUCTION_REQUIRED_PROVIDER_CATEGORIES if category not in provider_paths]
    limitations = ["Public data endpoints may be delayed, unavailable, blocked by network policy/403 restrictions, or revised after publication.", "No paid API, broker login, browser automation, or ETF Exit policy is used."]
    if "scores" not in provider_paths:
        limitations.append("Formal Tail Risk / BCD / MHS were not supplied by public fetchers; the daily pipeline will use existing fallback behavior for Tail Risk/BCD and MHS remains 0.0 unless supplied.")
    if "leadership" not in provider_paths:
        limitations.append("Leadership/Main-7 data unavailable; ETI-5 must remain unavailable unless a successful leadership source supplies it.")
    data_status = "public_full" if price_available and not unavailable and not failed else "public_partial" if price_available else "price_unavailable"
    return {
        "as_of": as_of.isoformat(),
        "generated_at": datetime.now(UTC).isoformat(),
        "attempted_sources": attempted,
        "successful_sources": successful,
        "failed_sources": failed,
        "stale_sources": stale,
        "unavailable_sources": unavailable,
        "missing_fields": missing_fields,
        "source_attempts": source_attempts,
        "provider_health_summary": health_payload.get("summary", {}),
        "provider_health": health_payload.get("providers", {}),
        "provider_csv_paths": dict(provider_paths),
        "production_required_categories": list(_PRODUCTION_REQUIRED_PROVIDER_CATEGORIES),
        "missing_production_csvs": missing_production_csvs,
        "production_required_csvs_present": not missing_production_csvs,
        "provider_csv_validation": _validate_written_provider_csvs(provider_paths, as_of),
        "data_status": data_status,
        "limitations": limitations,
        "optional_categories_unavailable": optional_categories,
        "sources": [result.as_dict() for result in fetch_results],
    }


def _validate_written_provider_csvs(provider_paths: Mapping[str, str], as_of: date) -> dict[str, Any]:
    validations: dict[str, Any] = {}
    price_path = provider_paths.get("price")
    if price_path:
        errors: list[str] = []
        path = Path(price_path)
        try:
            with path.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                fieldnames = tuple(reader.fieldnames or ())
                rows = list(reader)
        except OSError as exc:
            errors.append(f"cannot read CSV: {exc}")
            rows = []
            fieldnames = ()
        missing_columns = [field for field in _PRODUCTION_PRICE_FIELDS if field not in fieldnames]
        if missing_columns:
            errors.append("missing required columns: " + ", ".join(missing_columns))
        if len(rows) != 1:
            errors.append(f"expected exactly 1 row; got {len(rows)}")
        for row in rows:
            if row.get("trade_date") != as_of.isoformat():
                errors.append(f"trade_date {row.get('trade_date')!r} does not match {as_of.isoformat()}")
            for field in _REQUIRED_PRODUCTION_PRICE_VALUES:
                if _missing(row.get(field)):
                    errors.append(f"required field {field} is blank")
                    continue
                if _to_float(row.get(field)) is None:
                    errors.append(f"numeric field {field} is not parseable: {row.get(field)!r}")
            if _missing(row.get("provider_source")):
                errors.append("provider_source is required")
            if _missing(row.get("source_type")):
                errors.append("source_type is required")
        validations["price"] = {"path": str(path), "status": "passed" if not errors else "failed", "errors": errors}
    else:
        validations["price"] = {"status": "not_written", "errors": ["price.csv was not written"]}
    return validations


def build_provider_health(fetch_results: Sequence[PublicDataFetchResult], as_of: date) -> dict[str, Any]:
    """Build auditable provider-level health diagnostics from source attempts."""

    by_category: dict[str, list[PublicDataFetchResult]] = {}
    for result in fetch_results:
        by_category.setdefault(result.provider_category, []).append(result)

    providers = {
        f"{category}_provider": _provider_health_entry(category, results, as_of)
        for category, results in sorted(by_category.items())
    }
    summary = {
        "total_providers": len(providers),
        "healthy_providers": sorted(name for name, item in providers.items() if item.get("status") == "healthy"),
        "warning_providers": sorted(name for name, item in providers.items() if item.get("status") == "warning"),
        "failed_providers": sorted(name for name, item in providers.items() if item.get("status") == "failed"),
        "live_providers": sorted(name for name, item in providers.items() if item.get("source_type") == "live"),
        "local_fallback_providers": sorted(name for name, item in providers.items() if item.get("source_type") == "local_fallback"),
        "freshness_failed_providers": sorted(name for name, item in providers.items() if item.get("freshness_status") == "failed"),
        "zero_record_providers": sorted(name for name, item in providers.items() if item.get("records_loaded") == 0),
    }
    return {
        "as_of": as_of.isoformat(),
        "generated_at": datetime.now(UTC).isoformat(),
        "providers": providers,
        "summary": summary,
    }


def _provider_health_entry(category: str, results: Sequence[PublicDataFetchResult], as_of: date) -> dict[str, Any]:
    final = next((result for result in reversed(results) if result.success), results[-1])
    provider_name = f"{category}_provider"
    records_loaded = len(final.rows)
    required = category in _REQUIRED_PROVIDER_CATEGORIES
    freshness_status = "failed" if final.status == "stale" else "passed" if final.success else "not_applicable"
    source_type = _health_source_type(final)
    diagnostics_messages = [issue.message for result in results for issue in result.issues]
    attempted = [result.source_id for result in results]
    fallback_attempted = any(bool(result.raw_metadata.get("local_fallback")) or _health_source_type(result) == "local_fallback" for result in results)
    failed_attempt = next((result for result in reversed(results) if result.status == "failed"), None)
    exception_class = str(final.raw_metadata.get("exception_class") or (failed_attempt.raw_metadata.get("exception_class") if failed_attempt else "") or "")
    exception_message = str(final.raw_metadata.get("exception_message") or (failed_attempt.raw_metadata.get("exception_message") if failed_attempt else "") or "")
    validation_passed = final.success and final.status != "missing_fields"
    freshness_passed = freshness_status == "passed"

    blocking = (not final.success and required) or final.status in {"failed", "missing_fields", "stale"} or (required and records_loaded == 0)
    if blocking:
        status = "failed"
        final_decision = "block_pipeline"
    elif final.success and records_loaded > 0 and freshness_passed and source_type != "local_fallback" and not diagnostics_messages:
        status = "healthy"
        final_decision = "use_provider"
    else:
        status = "warning"
        final_decision = "use_provider_with_warning" if final.success else "optional_provider_unavailable"

    if source_type == "local_fallback" and status == "healthy":
        status = "warning"
        final_decision = "use_provider_with_warning"

    error_message = "; ".join(diagnostics_messages) if status == "failed" else ""
    diagnostics: dict[str, Any] = {
        "exception_class": exception_class,
        "exception_message": exception_message,
        "source_attempted": attempted,
        "fallback_attempted": fallback_attempted,
        "final_decision": final_decision,
        "source_selected": final.source_id if final.success else None,
        "source_selected_status": final.status,
        "source_selected_type": source_type,
        "validation_passed": validation_passed,
        "freshness_passed": freshness_passed,
        "issues": [issue.as_dict() for result in results for issue in result.issues],
    }
    if diagnostics_messages and status != "failed":
        diagnostics["messages"] = diagnostics_messages
    if source_type == "local_fallback":
        diagnostics.setdefault("messages", []).append("provider used local fallback")

    return {
        "provider_name": provider_name,
        "status": status,
        "as_of": _health_as_of(final, as_of),
        "source_type": source_type,
        "records_loaded": records_loaded,
        "fetch_duration_seconds": round(sum(float(result.raw_metadata.get("fetch_duration_seconds") or 0.0) for result in results), 6),
        "freshness_status": freshness_status,
        "error_message": error_message,
        "diagnostics": diagnostics,
    }


def _health_source_type(result: PublicDataFetchResult) -> str:
    raw_source_type = str(result.raw_metadata.get("source_type") or "").lower()
    if result.raw_metadata.get("local_fallback") or raw_source_type in {"local_csv_fallback", "local_json_fallback", "local_fallback"}:
        return "local_fallback"
    return "live"


def _health_as_of(result: PublicDataFetchResult, as_of: date) -> str:
    row = dict(result.rows[0] if result.rows else result.canonical_fields)
    parsed = _parse_date(row.get("date") or row.get("trade_date") or row.get("observed_at"))
    return (parsed or as_of).isoformat()


def _source_attempt_manifest(result: PublicDataFetchResult) -> dict[str, Any]:
    failure_reason = "; ".join(issue.message for issue in result.issues) if not result.success else ""
    source_type = str(result.raw_metadata.get("source_type") or "")
    if not source_type:
        source_type = "local_fallback" if result.raw_metadata.get("local_fallback") else "unknown"
    cache = result.raw_metadata.get("cache") if isinstance(result.raw_metadata.get("cache"), Mapping) else None
    url_fetch = result.raw_metadata.get("url_fetch") if isinstance(result.raw_metadata.get("url_fetch"), Mapping) else None
    return {
        "source_id": result.source_id,
        "source_name": result.source_name,
        "provider_category": result.provider_category,
        "source_type": source_type,
        "local_fallback": bool(result.raw_metadata.get("local_fallback")),
        "cache": dict(cache) if isinstance(cache, Mapping) else {"hit": False},
        "url_fetch": dict(url_fetch) if isinstance(url_fetch, Mapping) else {},
        "retry_attempts": int(url_fetch.get("attempts") or 0) if isinstance(url_fetch, Mapping) else 0,
        "attempted": True,
        "success": result.success,
        "status": result.status,
        "failure_reason": failure_reason,
        "stale_status": "stale" if result.status == "stale" else "fresh_or_not_applicable",
        "fields_extracted": sorted(str(key) for key, value in result.canonical_fields.items() if not _missing(value)),
    }


def load_source_config(config: Mapping[str, Any] | str | Path | None = None) -> dict[str, Any]:
    if config is None:
        path = Path(__file__).resolve().parents[2] / "config" / "public_data_sources.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {"sources": []}
    if isinstance(config, Mapping):
        return dict(config)
    text = Path(config).read_text(encoding="utf-8")
    if str(config).lower().endswith(('.yaml', '.yml')):
        return _parse_minimal_yaml(text)
    return json.loads(text)


def load_main7_symbols(path: str | Path | None = None) -> tuple[str, ...]:
    config_path = Path(path) if path else Path(__file__).resolve().parents[2] / "config" / "main7_symbols.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    values = payload.get("symbols", payload) if isinstance(payload, Mapping) else payload
    if not isinstance(values, list):
        raise ValueError("main7 config must be a JSON list or object with a symbols list")
    return tuple(str(item) for item in values)


def _result(source: PublicDataSource, status: str, issues: Sequence[PublicDataFetchIssue] = (), *, retrieved_at: str | None = None, rows: Sequence[Mapping[str, Any]] = (), canonical: Mapping[str, Any] | None = None, metadata: Mapping[str, Any] | None = None) -> PublicDataFetchResult:
    raw_metadata = dict(metadata or {})
    config = getattr(source, "config", {})
    if isinstance(config, Mapping):
        raw_metadata.setdefault("source_type", config.get("source_type") or config.get("adapter") or source.provider_category)
        if str(raw_metadata.get("source_type")) in {"local_csv_fallback", "local_json_fallback"}:
            raw_metadata.setdefault("local_fallback", True)
    fetch_diagnostics = _URL_FETCH_DIAGNOSTICS_BY_SOURCE.get(source.source_id)
    if fetch_diagnostics:
        raw_metadata.setdefault("url_fetch", dict(fetch_diagnostics))
    return PublicDataFetchResult(source.source_id, source.source_name, source.provider_category, status, tuple(rows), dict(canonical or {}), raw_metadata, tuple(issues), retrieved_at)


def _issue(source: PublicDataSource, severity: str, code: str, message: str, *, field: str | None = None) -> PublicDataFetchIssue:
    return PublicDataFetchIssue(severity, code, message, source.source_id, source.provider_category, field)



def _iter_configured_endpoint_configs(config: Mapping[str, Any], context: PublicDataFetchContext) -> list[tuple[Mapping[str, Any], str]]:
    if "fixture_path" in config:
        return [(config, str(config.get("fixture_path")))]
    templates = config.get("endpoint_url_templates") or config.get("urls")
    if isinstance(templates, list) and templates:
        endpoint_configs = [{**dict(config), "endpoint_url_template": str(template)} for template in templates]
        return [(endpoint_config, _render_url(endpoint_config, context)) for endpoint_config in endpoint_configs]
    return [(config, _render_url(config, context))]


def _fetch_configured_payloads(config: Mapping[str, Any], context: PublicDataFetchContext) -> list[Any]:
    if "fixture_path" in config:
        return [_fetch_json_payload(config, context)]
    templates = config.get("endpoint_url_templates") or config.get("urls")
    if isinstance(templates, list) and templates:
        return [_fetch_any_payload({**dict(config), "endpoint_url_template": str(template)}, context) for template in templates]
    months = int(config.get("lookback_months", 1) or 1)
    if months > 1:
        payloads = []
        seen: set[str] = set()
        current = date(context.as_of.year, context.as_of.month, 1)
        for _ in range(months):
            month_context = replace(context, as_of=current)
            url = _render_url(config, month_context)
            if url and url not in seen:
                seen.add(url)
                payloads.append(_fetch_any_payload(config, month_context))
            current = _previous_month(current)
        return list(reversed(payloads))
    return [_fetch_any_payload(config, context)]


def _fetch_symbol_payloads(config: Mapping[str, Any], context: PublicDataFetchContext, symbol: str) -> list[Any]:
    payloads = []
    months = int(config.get("lookback_months", 4) or 4)
    current = date(context.as_of.year, context.as_of.month, 1)
    for _ in range(months):
        symbol_context = replace(context, as_of=current)
        url = _render_url_for_symbol(config, symbol_context, symbol)
        payloads.append(_fetch_any_payload({**dict(config), "endpoint_url_template": url}, symbol_context))
        current = _previous_month(current)
    return list(reversed(payloads))


def _fetch_any_payload(config: Mapping[str, Any], context: PublicDataFetchContext) -> Any:
    if "fixture_path" in config:
        return json.loads(Path(str(config["fixture_path"])).read_text(encoding="utf-8"))
    url = _render_url(config, context)
    if not url:
        raise ValueError("source config missing endpoint_url_template/url or fixture_path")
    if url.startswith("file://"):
        text = Path(urllib.parse.urlparse(url).path).read_text(encoding="utf-8-sig")
    else:
        text = _fetch_url_text(config, context, url, accept="application/json,text/csv,text/html;q=0.9,*/*;q=0.5")
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return json.loads(text)
    return {"_text": text, "_url": url}



_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
_DEFAULT_MAX_REDIRECTS = 5
_DEFAULT_URL_FETCH_ATTEMPTS = 3
_DEFAULT_URL_FETCH_BACKOFF_SECONDS = 0.25
_URL_FETCH_DIAGNOSTICS_BY_SOURCE: dict[str, dict[str, Any]] = {}
_TWSE_OFFICIAL_REDIRECT_HOSTS = {"www.twse.com.tw", "wwwc.twse.com.tw", "openapi.twse.com.tw"}


def _fetch_url_text(config: Mapping[str, Any], context: PublicDataFetchContext, url: str, *, accept: str) -> str:
    """Fetch a configured public URL with bounded retries and redirects.

    urllib normally follows many redirects, but production TWSE runs can surface
    explicit HTTP 307 responses from official report endpoints. Handling them
    here keeps provider ordering fail-closed while allowing the same safe GET to
    continue only to trusted HTTPS/http official destinations. Live URL attempts
    are retried at most three times with short exponential backoff so transient
    CI egress/provider blips are observable without treating fallback data as
    production success.
    """

    current_url = url
    max_redirects = int(config.get("max_redirects", _DEFAULT_MAX_REDIRECTS) or 0)
    max_attempts = max(1, min(int(config.get("max_fetch_attempts", _DEFAULT_URL_FETCH_ATTEMPTS) or 1), _DEFAULT_URL_FETCH_ATTEMPTS))
    backoff_seconds = max(0.0, float(config.get("fetch_backoff_seconds", _DEFAULT_URL_FETCH_BACKOFF_SECONDS) or 0.0))
    headers = {"User-Agent": context.user_agent, "Accept": accept}
    source_id = str(config.get("source_id") or "unknown_source")
    diagnostics: dict[str, Any] = {
        "initial_url": url,
        "final_url": current_url,
        "max_attempts": max_attempts,
        "attempts": 0,
        "redirects": [],
        "errors": [],
    }
    _URL_FETCH_DIAGNOSTICS_BY_SOURCE[source_id] = diagnostics

    for redirect_count in range(max_redirects + 1):
        for attempt in range(1, max_attempts + 1):
            diagnostics["attempts"] = int(diagnostics.get("attempts") or 0) + 1
            diagnostics["final_url"] = current_url
            request = urllib.request.Request(current_url, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=context.timeout_seconds) as response:  # noqa: S310 - configured public endpoints only.
                    diagnostics["success"] = True
                    diagnostics["status"] = getattr(response, "status", 200)
                    return response.read().decode("utf-8-sig")
            except urllib.error.HTTPError as exc:
                if exc.code in _REDIRECT_STATUS_CODES:
                    if redirect_count >= max_redirects:
                        diagnostics.setdefault("errors", []).append({"url": current_url, "attempt": attempt, "error": f"HTTP redirect limit exceeded after {max_redirects} redirects"})
                        raise ValueError(f"HTTP redirect limit exceeded after {max_redirects} redirects from {url}") from exc
                    location = exc.headers.get("Location") if exc.headers else None
                    if not location:
                        diagnostics.setdefault("errors", []).append({"url": current_url, "attempt": attempt, "error": f"HTTP {exc.code} without Location header"})
                        raise ValueError(f"HTTP {exc.code} from {current_url} without Location header") from exc
                    target = _validated_redirect_url(config, current_url, str(location))
                    diagnostics.setdefault("redirects", []).append({"from": current_url, "to": target, "status": exc.code})
                    current_url = target
                    break
                diagnostics.setdefault("errors", []).append({"url": current_url, "attempt": attempt, "error": f"HTTP {exc.code}"})
                if attempt >= max_attempts:
                    diagnostics["success"] = False
                    raise ValueError(f"HTTP {exc.code} from {current_url} after {attempt} attempts") from exc
                time.sleep(backoff_seconds * (2 ** (attempt - 1)))
            except urllib.error.URLError as exc:
                diagnostics.setdefault("errors", []).append({"url": current_url, "attempt": attempt, "error": str(exc)})
                if attempt >= max_attempts:
                    diagnostics["success"] = False
                    raise ValueError(f"URL fetch failed from {current_url} after {attempt} attempts: {exc}") from exc
                time.sleep(backoff_seconds * (2 ** (attempt - 1)))
        else:
            continue
        continue
    diagnostics["success"] = False
    raise ValueError(f"HTTP redirect limit exceeded after {max_redirects} redirects from {url}")


def _validated_redirect_url(config: Mapping[str, Any], current_url: str, location: str) -> str:
    target = urllib.parse.urljoin(current_url, location.strip())
    current_parts = urllib.parse.urlparse(current_url)
    target_parts = urllib.parse.urlparse(target)
    if target_parts.scheme not in {"http", "https"}:
        raise ValueError(f"refusing redirect from {current_url} to unsupported scheme: {target}")
    if current_parts.scheme == "https" and target_parts.scheme != "https":
        raise ValueError(f"refusing HTTPS downgrade redirect from {current_url} to {target}")
    target_host = (target_parts.hostname or "").lower()
    allowed_hosts = _allowed_redirect_hosts(config, current_url)
    if target_host not in allowed_hosts:
        allowed = ", ".join(sorted(allowed_hosts))
        raise ValueError(f"refusing redirect from {current_url} to unapproved host {target_host!r}; allowed hosts: {allowed}")
    return target


def _allowed_redirect_hosts(config: Mapping[str, Any], current_url: str) -> set[str]:
    current_host = (urllib.parse.urlparse(current_url).hostname or "").lower()
    hosts = {current_host} if current_host else set()
    configured = config.get("allowed_redirect_hosts") or ()
    if isinstance(configured, str):
        configured = (configured,)
    if isinstance(configured, Sequence):
        hosts.update(str(host).lower() for host in configured if str(host).strip())
    source_type = str(config.get("source_type") or config.get("adapter") or "").lower()
    endpoint = str(config.get("endpoint_url_template") or config.get("symbol_endpoint_url_template") or config.get("url") or "").lower()
    if source_type.startswith("twse") or "twse.com.tw" in endpoint or "openapi.twse.com.tw" in endpoint:
        hosts.update(_TWSE_OFFICIAL_REDIRECT_HOSTS)
    return hosts

def _previous_month(value: date) -> date:
    return date(value.year - (1 if value.month == 1 else 0), 12 if value.month == 1 else value.month - 1, 1)


def _render_url_for_symbol(config: Mapping[str, Any], context: PublicDataFetchContext, symbol: str) -> str:
    template = str(config.get("symbol_endpoint_url_template") or config.get("endpoint_url_template") or config.get("url") or "")
    values = {"symbol": symbol, "stock_no": symbol, "as_of": context.as_of.isoformat(), "yyyymmdd": context.as_of.strftime("%Y%m%d"), "yyyymm": context.as_of.strftime("%Y%m"), "yyyy": context.as_of.strftime("%Y"), "mm": context.as_of.strftime("%m"), "dd": context.as_of.strftime("%d")}
    return template.format(**values)


def _parse_fmtqik_price_bars(payload: Any, as_of: date) -> list[MarketPriceBar]:
    rows = _payload_rows(payload)
    bars: list[MarketPriceBar] = []
    for row in rows:
        observed = _parse_date(_first(row, "日期", "Date", "date", "trade_date"))
        if observed is None or observed > as_of:
            continue
        close = _to_float(_first(row, "發行量加權股價指數", "TAIEX", "taiex_close", "close"))
        turnover = _to_float(_first(row, "成交金額", "Trading Value", "turnover_amount", "turnover"))
        if close is not None:
            bars.append(MarketPriceBar(observed_at=observed, close=close, turnover_amount=turnover or 0.0))
    return bars


def _parse_twse_margin_balance(payload: Any) -> float | None:
    rows = _payload_rows(payload)
    if not rows:
        return None
    total_values: list[float] = []
    financing_values: list[float] = []
    row_values: list[float] = []
    for row in rows:
        value = _to_float(_first(row, "MarginPurchaseTodayBalance", "Margin Purchase Today Balance", "融資今日餘額", "融資餘額", "今日餘額", "TodayBalance"))
        if value is None:
            continue
        label = str(_first(row, "股票代號", "證券代號", "項目", "Name", "name") or "")
        normalized_label = re.sub(r"\s+", "", label)
        if any(token in normalized_label for token in ("合計", "總計", "Total", "total")):
            total_values.append(value)
        elif _is_margin_financing_balance_label(normalized_label):
            financing_values.append(value)
        else:
            row_values.append(value)
    values = total_values or financing_values or row_values
    return sum(values) if values else None


def _is_margin_financing_balance_label(label: str) -> bool:
    lower = label.lower()
    if "融券" in label or "short" in lower:
        return False
    if "金額" in label or "amount" in lower:
        return False
    return "融資" in label or ("margin" in lower and "purchase" in lower)


def _table_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    output: list[Mapping[str, Any]] = []
    tables = payload.get("tables")
    if not isinstance(tables, list):
        return output
    for table in tables:
        if not isinstance(table, Mapping):
            continue
        fields = table.get("fields")
        data = table.get("data")
        if not isinstance(fields, list) or not isinstance(data, list):
            continue
        field_names = [str(field) for field in fields]
        for raw_row in data:
            if isinstance(raw_row, Mapping):
                output.append(raw_row)
            elif isinstance(raw_row, list):
                output.append(_row_from_fields(field_names, raw_row))
    return output


def _row_from_fields(fields: Sequence[str], values: Sequence[Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    row: dict[str, Any] = {}
    for index, field in enumerate(fields):
        if index >= len(values):
            break
        count = counts.get(field, 0) + 1
        counts[field] = count
        key = field if count == 1 else f"{field}_{count}"
        row[key] = values[index]
    return row


def _parse_t86_foreign_flow(payload: Any, as_of: date) -> dict[str, Any] | None:
    rows = _payload_rows(payload)
    net_values = []
    for row in rows:
        net = _to_float(
            _first(
                row,
                "外陸資買賣超股數(不含自營商)",
                "外陸資買賣超股數(不含外資自營商)",
                "外資及陸資買賣超股數(不含自營商)",
                "外資及陸資買賣超股數(不含外資自營商)",
                "外資及陸資(不含自營商)買賣超股數",
                "外資及陸資(不含外資自營商)買賣超股數",
                "外陸資(不含自營商)買賣超股數",
                "外陸資(不含外資自營商)買賣超股數",
                "外資及陸資買賣超股數",
                "外陸資買賣超股數",
                "Foreign_Investor_Buy_Sell_Difference",
                "Foreign Investor Buy/Sell Difference",
                "foreign_spot_net_buy",
            )
        )
        if net is None:
            buy = _to_float(
                _first(
                    row,
                    "外陸資買進股數(不含自營商)",
                    "外陸資買進股數(不含外資自營商)",
                    "外資及陸資買進股數(不含自營商)",
                    "外資及陸資買進股數(不含外資自營商)",
                    "外資及陸資(不含自營商)買進股數",
                    "外資及陸資(不含外資自營商)買進股數",
                    "外陸資(不含自營商)買進股數",
                    "外陸資(不含外資自營商)買進股數",
                    "Foreign_Investor_Buy",
                    "Foreign Investor Buy",
                )
            )
            sell = _to_float(
                _first(
                    row,
                    "外陸資賣出股數(不含自營商)",
                    "外陸資賣出股數(不含外資自營商)",
                    "外資及陸資賣出股數(不含自營商)",
                    "外資及陸資賣出股數(不含外資自營商)",
                    "外資及陸資(不含自營商)賣出股數",
                    "外資及陸資(不含外資自營商)賣出股數",
                    "外陸資(不含自營商)賣出股數",
                    "外陸資(不含外資自營商)賣出股數",
                    "Foreign_Investor_Sell",
                    "Foreign Investor Sell",
                )
            )
            if buy is not None and sell is not None:
                net = buy - sell
        if net is not None:
            net_values.append(net)
    if not net_values:
        return None
    total_net = sum(net_values)
    return {"date": as_of.isoformat(), "foreign_spot_net_buy": total_net, "foreign_spot_net_sell": abs(min(total_net, 0.0)), "foreign_spot_large_sell": total_net <= -10_000_000_000, "foreign_large_sell": total_net <= -10_000_000_000, "futures_hedging_increases": False, "futures_hedging_significant": False}


def _parse_taifex_fx_rows(payload: Any, as_of: date) -> list[dict[str, Any]]:
    output = []
    for row in _payload_rows(payload):
        observed = _parse_date(_first(row, "日期", "Date", "date", "交易日期", "TradeDate"))
        if observed is None or observed > as_of:
            continue
        value = _to_float(_first(row, "美元／新台幣", "美元/新台幣", "USD/NTD", "USD/TWD", "USDTWD", "usd_twd"))
        if value is not None:
            output.append({"date": observed.isoformat(), "usd_twd": value})
    return output


def _parse_cbc_fx_rows(payload: Any, as_of: date) -> list[dict[str, Any]]:
    output = []
    for row in _payload_rows(payload):
        observed = _parse_date(_first(row, "Date", "date", "TIME_PERIOD", "time", "日期"))
        if observed is None or observed > as_of:
            continue
        value = _to_float(_first(row, "NTD/USD", "NTD-USD", "USD/TWD", "USDTWD", "NT$/US$", "VALUE", "value", "rate", "Exchange Rate"))
        if value is not None:
            output.append({"date": observed.isoformat(), "usd_twd": value})
    return output


def _parse_twse_breadth(payload: Any, as_of: date) -> dict[str, Any] | None:
    rows = _payload_rows(payload)
    adv = dec = None
    for row in rows:
        label = str(_first(row, "類型", "Type", "name", "Name", "指數", "證券名稱") or "")
        label_lower = label.lower()
        if "上漲" in label or label_lower in {"up", "advance", "advancing issues"}:
            adv = _to_twse_count(_first(row, "家數", "Count", "count", "advancing_issues", "上漲家數", "整體市場", "股票"))
        if "下跌" in label or label_lower in {"down", "decline", "declining issues"}:
            dec = _to_twse_count(_first(row, "家數", "Count", "count", "declining_issues", "下跌家數", "整體市場", "股票"))
        adv = adv if adv is not None else _to_twse_count(_first(row, "上漲家數", "advancing_issues"))
        dec = dec if dec is not None else _to_twse_count(_first(row, "下跌家數", "declining_issues"))
    if adv is None or dec is None:
        return None
    return {"date": as_of.isoformat(), "advancing_issues": int(adv), "declining_issues": int(dec), "index_down": dec > adv, "declining_gt_advancing_consecutive_days": 1 if dec > adv else 0, "breadth_weakens_for_2_days": False}


def _to_twse_count(value: Any) -> float | None:
    if isinstance(value, str):
        value = value.split("(", 1)[0].strip()
    return _to_float(value)


def _parse_taifex_futures(payload: Any, as_of: date) -> dict[str, Any] | None:
    for row in _payload_rows(payload):
        contract = str(_first(row, "契約", "商品代號", "Contract", "ContractCode", "product_id", "futures_source_contract") or "").upper()
        if contract and not contract.startswith("TX"):
            continue
        close = _to_float(_first(row, "收盤價", "Close", "close", "txf_close"))
        settle = _to_float(_first(row, "結算價", "Settlement Price", "SettlementPrice", "settlement", "txf_settlement"))
        volume = _to_float(_first(row, "成交量", "Volume", "volume", "txf_volume"))
        oi = _to_float(_first(row, "未沖銷契約數", "Open Interest", "OpenInterest", "open_interest", "txf_open_interest"))
        if close is not None or settle is not None:
            return {"date": as_of.isoformat(), "txf_close": close or settle, "txf_settlement": settle or close, "txf_volume": volume, "txf_open_interest": oi, "futures_source_contract": contract or "TX"}
    return None


def _parse_taifex_options(payload: Any, as_of: date) -> dict[str, Any]:
    row_out: dict[str, Any] = {"date": as_of.isoformat()}
    for row in _payload_rows(payload):
        pcr = _to_float(_first(row, "賣權/買權比", "Put/Call Ratio", "PutCallVolumeRatio", "put_call_ratio", "txo_put_call_ratio"))
        if pcr is not None:
            row_out["txo_put_call_ratio"] = pcr
            row_out["txo_put_volume"] = _to_float(_first(row, "賣權成交量", "Put Volume", "PutVolume", "put_volume", "txo_put_volume"))
            row_out["txo_call_volume"] = _to_float(_first(row, "買權成交量", "Call Volume", "CallVolume", "call_volume", "txo_call_volume"))
        vix = _to_float(_first(row, "臺指選擇權波動率指數", "TAIFEX VIX", "VIX", "vix", "taifex_vix"))
        if vix is not None:
            row_out["taifex_vix"] = vix
    return row_out


def _parse_stock_closes(payload: Any, as_of: date) -> list[float]:
    closes = []
    for row in _payload_rows(payload):
        observed = _parse_date(_first(row, "日期", "Date", "date", "trade_date"))
        if observed is not None and observed > as_of:
            continue
        close = _to_float(_first(row, "收盤價", "Closing Price", "Close", "close"))
        if close is not None:
            closes.append(close)
    return closes


def _payload_rows(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, Mapping) and "_text" in payload:
        return _html_table_rows(str(payload.get("_text") or ""))
    rows: list[Any] = []
    if isinstance(payload, Mapping):
        rows = list(_table_rows(payload))
        if not rows:
            rows = _numbered_table_rows(payload)
        if not rows:
            for rows_path in ("data", "DataSet", "dataset", "Dataset", "rows", "items"):
                rows = _extract_rows(payload, {"rows_path": rows_path})
                if rows:
                    break
    elif isinstance(payload, list):
        rows = payload
    return _flatten_mapping_rows(rows)


def _numbered_table_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    output: list[Mapping[str, Any]] = []
    numbered_keys = sorted(
        (key for key in payload if re.fullmatch(r"data\d+", str(key))),
        key=lambda item: int(str(item)[4:]),
    )
    for data_key in numbered_keys:
        data = payload.get(data_key)
        fields = payload.get(f"fields{str(data_key)[4:]}")
        if not isinstance(data, list) or not isinstance(fields, list):
            continue
        field_names = [str(field) for field in fields]
        for raw_row in data:
            if isinstance(raw_row, Mapping):
                output.append(raw_row)
            elif isinstance(raw_row, list):
                output.append(_row_from_fields(field_names, raw_row))
    return output


def _flatten_mapping_rows(rows: Any) -> list[Mapping[str, Any]]:
    output: list[Mapping[str, Any]] = []
    if isinstance(rows, Mapping):
        output.append(rows)
    elif isinstance(rows, list):
        for item in rows:
            output.extend(_flatten_mapping_rows(item))
    return output


def _html_table_rows(text: str) -> list[Mapping[str, Any]]:
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", text, flags=re.I | re.S):
        cells = [html.unescape(re.sub(r"<.*?>", "", cell)).strip() for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.I | re.S)]
        if cells:
            rows.append(cells)
    if not rows:
        return []
    header = rows[0]
    return [{header[index]: cell for index, cell in enumerate(row) if index < len(header)} for row in rows[1:]]


def _first(row: Mapping[str, Any], *names: str) -> Any:
    normalized = {_normalize_label(key): value for key, value in row.items()}
    for name in names:
        if name in row and not _missing(row.get(name)):
            return row.get(name)
        value = normalized.get(_normalize_label(name))
        if not _missing(value):
            return value
    return None


def _normalize_label(value: Any) -> str:
    return re.sub(r"[\s_()（）/／%-]+", "", str(value)).lower()


def _pct_change_from_rows(rows: Sequence[Mapping[str, Any]], periods: int, field: str) -> float | None:
    if len(rows) <= periods:
        return None
    current = _to_float(rows[-1].get(field))
    previous = _to_float(rows[-1 - periods].get(field))
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / previous * 100.0


def _fetch_json_payload(config: Mapping[str, Any], context: PublicDataFetchContext) -> Any:
    if "fixture_path" in config:
        return json.loads(Path(str(config["fixture_path"])).read_text(encoding="utf-8"))
    url = _render_url(config, context)
    if not url:
        raise ValueError("source config missing endpoint_url_template/url or fixture_path")
    if url.startswith("file://"):
        return json.loads(Path(urllib.parse.urlparse(url).path).read_text(encoding="utf-8"))
    body = _fetch_url_text(config, context, url, accept="application/json,text/csv;q=0.8,*/*;q=0.5")
    return json.loads(body)


def _render_url(config: Mapping[str, Any], context: PublicDataFetchContext) -> str:
    template = str(config.get("endpoint_url_template") or config.get("url") or "")
    if not template:
        return ""
    twse_date = context.as_of.strftime("%Y%m%d")
    values = {"as_of": context.as_of.isoformat(), "yyyymmdd": twse_date, "yyyymm": context.as_of.strftime("%Y%m"), "yyyy": context.as_of.strftime("%Y"), "mm": context.as_of.strftime("%m"), "dd": context.as_of.strftime("%d")}
    return template.format(**values)


def _extract_rows(payload: Any, config: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    path = str(config.get("rows_path") or "")
    target = _get_path(payload, path) if path else payload
    if isinstance(target, Mapping):
        for key in ("data", "rows", "items"):
            if isinstance(target.get(key), list):
                target = target[key]
                break
    if not isinstance(target, list):
        return []
    fields = config.get("fields")
    if not fields and isinstance(payload, Mapping):
        fields = payload.get("fields")
    return [_row_to_mapping(row, fields) for row in target]


def _extract_row(payload: Any, config: Mapping[str, Any], as_of: date) -> Mapping[str, Any] | None:
    rows = _extract_rows(payload, config)
    if not rows and isinstance(payload, Mapping):
        return payload
    date_fields = tuple(str(item) for item in config.get("date_fields", ("date", "trade_date", "observed_at", "日期")))
    for row in rows:
        for field_name in date_fields:
            if field_name in row and _parse_date(row[field_name]) == as_of:
                return row
    return rows[-1] if len(rows) == 1 else None


def _row_to_mapping(row: Any, fields: Any) -> Mapping[str, Any]:
    if isinstance(row, Mapping):
        return row
    if isinstance(row, (list, tuple)) and isinstance(fields, list):
        return {str(field): row[index] if index < len(row) else None for index, field in enumerate(fields)}
    return {}


def _get_path(payload: Any, path: str) -> Any:
    target = payload
    for part in path.split(".") if path else []:
        if isinstance(target, Mapping):
            target = target.get(part)
        elif isinstance(target, list) and part.isdigit():
            target = target[int(part)]
        else:
            return None
    return target


def _map_fields(row: Mapping[str, Any], mapping: Mapping[str, Any]) -> dict[str, Any]:
    if not mapping:
        return {str(key): value for key, value in row.items()}
    output: dict[str, Any] = {}
    for canonical, source_field in mapping.items():
        if isinstance(source_field, list):
            value = next((row.get(str(item)) for item in source_field if str(item) in row and not _missing(row.get(str(item)))), None)
        else:
            value = row.get(str(source_field))
        output[str(canonical)] = value
    for key, value in row.items():
        output.setdefault(str(key), value)
    return output


def _normalize_provider_row(category: str, row: Mapping[str, Any], as_of: date) -> dict[str, Any]:
    output = {str(key): _clean_value(value) for key, value in row.items()}
    output.setdefault("date", output.get("observed_at") or output.get("trade_date") or as_of.isoformat())
    if category == "price":
        renames = {"close": "taiex_close", "ma5": "taiex_ma5", "ma20": "taiex_ma20", "ma60": "taiex_ma60", "ma20_slope": "taiex_ma20_slope"}
        for source, dest in renames.items():
            if source in output and dest not in output:
                output[dest] = output[source]
    if category == "breadth" and "advancing_issues" in output and "declining_issues" in output:
        adv = _to_float(output.get("advancing_issues")) or 0.0
        dec = _to_float(output.get("declining_issues")) or 0.0
        output.setdefault("declining_issues_significantly_gt_advancing", dec > adv * 1.5)
    if category == "foreign_flow":
        sell = _to_float(output.get("foreign_spot_net_sell"))
        buy = _to_float(output.get("foreign_spot_net_buy"))
        if sell is None and buy is not None:
            output["foreign_spot_net_sell"] = buy < 0
    return output


def _parse_price_bars(payload: Any, as_of: date) -> list[MarketPriceBar]:
    rows = _extract_rows(payload, {"rows_path": "data"}) if isinstance(payload, Mapping) else []
    fields = [str(field).strip().lower() for field in payload.get("fields", [])] if isinstance(payload, Mapping) else []
    bars: list[MarketPriceBar] = []
    for row in rows:
        date_value = _value_by_names(row, fields, ("date", "日期"), 0)
        observed = _parse_date(date_value)
        if observed is None or observed > as_of:
            continue
        close = _to_float(_value_by_names(row, fields, ("closing index", "close", "收盤指數", "taiex_close"), -1))
        if close is None:
            continue
        bars.append(MarketPriceBar(observed_at=observed, close=close, turnover_amount=_to_float(row.get("turnover_amount") or row.get("turnover")) or 0.0, open=_to_float(_value_by_names(row, fields, ("opening index", "open"), 1)), high=_to_float(_value_by_names(row, fields, ("highest index", "high"), 2)), low=_to_float(_value_by_names(row, fields, ("lowest index", "low"), 3)), volume=_to_float(row.get("volume"))))
    return bars


def _value_by_names(row: Mapping[str, Any], fields: Sequence[str], names: Sequence[str], fallback_index: int) -> Any:
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    for name in names:
        if name in lowered:
            return lowered[name]
    if fields and fallback_index >= 0 and fallback_index < len(fields):
        return row.get(fields[fallback_index])
    if fields and fallback_index < 0 and len(fields) >= abs(fallback_index):
        return row.get(fields[fallback_index])
    return None


def _local_price_is_stale(row: Mapping[str, Any], config: Mapping[str, Any], as_of: date) -> bool:
    freshness = config.get("freshness_rules") if isinstance(config.get("freshness_rules"), Mapping) else {}
    max_lag_days = int(freshness.get("max_lag_days", 0) or 0) if isinstance(freshness, Mapping) else 0
    row_date = _parse_date(row.get("date") or row.get("trade_date") or row.get("observed_at"))
    if row_date is None or row_date > as_of:
        return True
    return (as_of - row_date).days > max_lag_days


def _local_fallback_path(config: Mapping[str, Any]) -> str:
    value = config.get("path") or config.get("file_path") or config.get("fixture_path")
    if value:
        return str(value)
    url = str(config.get("url") or "")
    if url.startswith("file://"):
        return urllib.parse.urlparse(url).path
    return ""


def _read_local_fallback_rows(path: Path, source_type: str, config: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if source_type == "local_json_fallback" or path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, Mapping)]
        rows = _extract_rows(payload, config)
        if rows:
            return rows
        return [payload] if isinstance(payload, Mapping) else []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _select_local_fallback_row(rows: Sequence[Mapping[str, Any]], config: Mapping[str, Any], as_of: date) -> Mapping[str, Any] | None:
    date_fields = tuple(str(item) for item in config.get("date_fields", ("date", "trade_date", "observed_at", "日期")))
    for row in rows:
        for field_name in date_fields:
            if field_name in row and _parse_date(row[field_name]) == as_of:
                return row
    return rows[-1] if len(rows) == 1 else None


def _write_csv(path: Path, fields: Sequence[str], row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        writer.writerow({field: _csv_value(row.get(field)) for field in fields})


def _provider_field_map() -> dict[str, Any]:
    return {
        "categories": {
            "price": {"taiex_close": "close", "taiex_ma5": "ma5", "taiex_ma20": "ma20", "taiex_ma60": "ma60"},
        },
        "notes": "Generated by public-data fetchers; no model scoring fields are remapped here.",
    }


def _scores_are_formal_or_explicit(result: PublicDataFetchResult) -> bool:
    row = dict(result.rows[0] if result.rows else result.canonical_fields)
    status = str(row.get("score_status") or row.get("scores_status") or "").lower()
    return status in {"formal", "provisional_proxy", "deterministic_provisional"} and any(not _missing(row.get(field)) for field in ("tail_risk", "bcd", "mhs"))


def _is_stale(row: Mapping[str, Any], config: Mapping[str, Any], as_of: date) -> bool:
    freshness = config.get("freshness_rules") if isinstance(config.get("freshness_rules"), Mapping) else {}
    max_lag_days = int(freshness.get("max_lag_days", 0) or 0) if isinstance(freshness, Mapping) else 0
    if max_lag_days <= 0:
        return False
    row_date = _parse_date(row.get("date") or row.get("trade_date") or row.get("observed_at"))
    return row_date is None or (as_of - row_date).days > max_lag_days


def _has_price_minimum(row: Mapping[str, Any]) -> bool:
    return all(not _missing(row.get(field)) for field in ("taiex_close", "taiex_ma5", "taiex_ma20", "taiex_ma60", "taiex_ma20_slope"))



def _date_lag_failed(observed: date | None, config: Mapping[str, Any], as_of: date) -> bool:
    if observed is None:
        return True
    freshness = config.get("freshness_rules") if isinstance(config.get("freshness_rules"), Mapping) else {}
    max_lag_days = int(freshness.get("max_lag_days", 0) or 0) if isinstance(freshness, Mapping) else 0
    return max_lag_days >= 0 and (as_of - observed).days > max_lag_days

def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip().replace("/", "-")
    if not text:
        return None
    compact = re.sub(r"[^0-9]", "", text.split()[0])
    if len(compact) == 8 and "-" not in text.split()[0]:
        try:
            return date(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))
        except ValueError:
            return None
    parts = text.split()[0].split("-")
    try:
        if len(parts) == 3 and len(parts[0]) <= 3:
            return date(int(parts[0]) + 1911, int(parts[1]), int(parts[2]))
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text in {"--", "-", ""}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _clean_value(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        lower = text.lower()
        if lower in {"true", "false"}:
            return lower == "true"
        parsed = _to_float(text)
        return parsed if parsed is not None and any(char.isdigit() for char in text) else value.strip()
    return value


def _csv_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _missing(value: Any) -> bool:
    return value is None or value == "" or value == []


def _parse_minimal_yaml(text: str) -> dict[str, Any]:
    # Keep YAML optional without adding a dependency. JSON is valid YAML, which
    # covers the supported non-JSON use in tests/operators for this project.
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("YAML source config requires JSON-compatible YAML in this environment") from exc
