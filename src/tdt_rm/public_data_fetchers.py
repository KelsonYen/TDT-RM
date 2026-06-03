"""Public data fetchers for generating daily provider CSV inputs.

This module is intentionally limited to public-data acquisition and provider CSV
normalization. It does not score TDT-RM signals and does not change TCWRS,
ETI-5, Crash Probability, Bear Trend Filter, CAL, or decision-matrix logic.
"""

from __future__ import annotations

import csv
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .market_data import MarketPriceBar, derive_price_features

_REQUIRED_PROVIDER_CATEGORIES = {"price"}
_DEFAULT_OPTIONAL_CATEGORIES = ("foreign_flow", "fx", "breadth", "leadership", "margin", "scores", "derivatives")
_PROVIDER_CSV_NAMES = {
    "price": "price.csv",
    "foreign_flow": "foreign_flow.csv",
    "fx": "fx.csv",
    "breadth": "breadth.csv",
    "leadership": "leadership.csv",
    "margin": "margin.csv",
    "scores": "scores.csv",
}
_PROVIDER_FIELDS = {
    "price": ("date", "taiex_close", "taiex_ma5", "taiex_ma20", "taiex_ma60", "taiex_ma20_slope", "one_day_return_pct", "two_day_return_pct", "turnover_amount", "ma20_turnover"),
    "foreign_flow": ("date", "foreign_spot_net_buy", "foreign_spot_net_sell", "foreign_spot_net_sell_consecutive_days", "foreign_large_sell", "foreign_spot_large_sell", "futures_hedging_increases", "futures_hedging_significant"),
    "fx": ("date", "usd_twd", "usd_twd_3d_change_pct", "usd_twd_5d_change_pct", "twd_appreciates", "twd_stable", "twd_depreciates_significantly"),
    "breadth": ("date", "advancing_issues", "declining_issues", "index_down", "declining_issues_significantly_expand", "declining_issues_significantly_gt_advancing", "declining_gt_advancing_consecutive_days", "breadth_weakens_for_2_days"),
    "leadership": ("date", "count_main_7_below_ma20", "count_main_7_below_ma60", "majority_main_7_assets_above_ma20", "main_7_symbols", "main_7_below_ma20_symbols"),
    "margin": ("date", "margin_balance_5d_flat_or_down", "hot_stock_margin_fast_increase", "margin_balance_5d_increases", "index_5d_return_pct", "margin_balance_5d_decline_pct", "margin_not_retreating"),
    "scores": ("date", "tail_risk", "bcd", "mhs", "score_status", "score_notes"),
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
    data_status: str = "unavailable"
    issues: tuple[PublicDataFetchIssue, ...] = ()
    manifest: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "output_dir": self.output_dir,
            "provider_csv_paths": dict(self.provider_csv_paths),
            "provider_field_map_path": self.provider_field_map_path,
            "fetch_manifest_path": self.fetch_manifest_path,
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
            adapter = str(item.get("adapter") or item.get("provider_category") or "generic_json")
            if adapter == "twse_taiex_price" or item.get("provider_category") == "price":
                sources.append(TWSETAIEXPriceSource(item))
            elif adapter == "leadership_main7":
                sources.append(LeadershipMain7Source(item))
            else:
                sources.append(GenericJsonPublicDataSource(item))
        return cls(sources)

    def fetch_all(self, context: PublicDataFetchContext) -> tuple[PublicDataFetchResult, ...]:
        return tuple(source.fetch(context) for source in self.sources)

    def source_ids(self) -> tuple[str, ...]:
        return tuple(source.source_id for source in self.sources)


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
            return _result(self, "failed", (_issue(self, "error", "fetch_failed", str(exc)),), retrieved_at=retrieved_at)


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
            if len(bars) < max(60, int(self.config.get("min_bars", 1))):
                # Some fixtures/configs provide a direct canonical row instead of history.
                row = _extract_row(payload, self.config, context.as_of)
                if isinstance(row, Mapping):
                    mapped = _map_fields(row, self.config.get("field_mapping") or self.config.get("field_extraction_mapping") or {})
                    normalized = _normalize_provider_row("price", mapped, context.as_of)
                    if _has_price_minimum(normalized):
                        return _result(self, "success", retrieved_at=retrieved_at, rows=(normalized,), canonical=normalized, metadata={"endpoint": _render_url(self.config, context), "mode": "canonical_row"})
                return _result(self, "failed", (_issue(self, "error", "insufficient_price_history", f"price source returned {len(bars)} bars; cannot derive required price fields"),), retrieved_at=retrieved_at)
            bars = tuple(sorted(bars, key=lambda item: item.observed_at))
            features = derive_price_features(bars)
            normalized = _normalize_provider_row("price", features, context.as_of)
            normalized["date"] = context.as_of.isoformat()
            return _result(self, "success", retrieved_at=retrieved_at, rows=(normalized,), canonical=normalized, metadata={"endpoint": _render_url(self.config, context), "bar_count": len(bars), "mode": "price_history"})
        except Exception as exc:  # noqa: BLE001
            return _result(self, "failed", (_issue(self, "error", "fetch_failed", str(exc)),), retrieved_at=retrieved_at)


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
            return _result(self, "failed", (_issue(self, "error", "fetch_failed", str(exc)),), retrieved_at=retrieved_at)


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
        fields = tuple(field for field in _PROVIDER_FIELDS[result.provider_category] if field in row or field == "date")
        _write_csv(path, fields, row)
        provider_paths[result.provider_category] = str(path)

    field_map_path = destination / "provider_field_map.json"
    field_map_path.write_text(json.dumps(_provider_field_map(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = build_fetch_manifest(fetch_results, provider_paths, as_of)
    data_status = str(manifest["data_status"])
    manifest_path = destination / "fetch_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ProviderCsvWriteResult(str(destination), provider_paths, str(field_map_path), str(manifest_path), data_status, tuple(issues), manifest)


def build_fetch_manifest(fetch_results: Sequence[PublicDataFetchResult], provider_paths: Mapping[str, str], as_of: date) -> dict[str, Any]:
    attempted = [result.source_id for result in fetch_results]
    successful = [result.source_id for result in fetch_results if result.success]
    failed = [result.source_id for result in fetch_results if result.status == "failed"]
    stale = [result.source_id for result in fetch_results if result.status == "stale"]
    missing_fields = [issue.as_dict() for result in fetch_results for issue in result.issues if issue.code in {"missing_field", "constituents_missing", "constituent_field_missing"} or result.status == "missing_fields"]
    unavailable = [result.source_id for result in fetch_results if result.status in {"unavailable", "missing_fields", "stale"}]
    price_available = "price" in provider_paths
    optional_categories = sorted(set(_DEFAULT_OPTIONAL_CATEGORIES) - set(provider_paths))
    limitations = ["Public data endpoints may be delayed, unavailable, or revised after publication.", "No paid API, broker login, browser automation, or ETF Exit policy is used."]
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
        "provider_csv_paths": dict(provider_paths),
        "data_status": data_status,
        "limitations": limitations,
        "optional_categories_unavailable": optional_categories,
        "sources": [result.as_dict() for result in fetch_results],
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
    return PublicDataFetchResult(source.source_id, source.source_name, source.provider_category, status, tuple(rows), dict(canonical or {}), dict(metadata or {}), tuple(issues), retrieved_at)


def _issue(source: PublicDataSource, severity: str, code: str, message: str, *, field: str | None = None) -> PublicDataFetchIssue:
    return PublicDataFetchIssue(severity, code, message, source.source_id, source.provider_category, field)


def _fetch_json_payload(config: Mapping[str, Any], context: PublicDataFetchContext) -> Any:
    if "fixture_path" in config:
        return json.loads(Path(str(config["fixture_path"])).read_text(encoding="utf-8"))
    url = _render_url(config, context)
    if not url:
        raise ValueError("source config missing endpoint_url_template/url or fixture_path")
    if url.startswith("file://"):
        return json.loads(Path(urllib.parse.urlparse(url).path).read_text(encoding="utf-8"))
    request = urllib.request.Request(url, headers={"User-Agent": context.user_agent, "Accept": "application/json,text/csv;q=0.8,*/*;q=0.5"})
    try:
        with urllib.request.urlopen(request, timeout=context.timeout_seconds) as response:  # noqa: S310 - configured public endpoints only.
            body = response.read().decode("utf-8-sig")
    except urllib.error.HTTPError as exc:
        raise ValueError(f"HTTP {exc.code} from {url}") from exc
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
        renames = {"close": "taiex_close", "ma5": "taiex_ma5", "ma20": "taiex_ma20", "ma60": "taiex_ma60"}
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


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip().replace("/", "-")
    if not text:
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
