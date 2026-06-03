"""Provider registry and local-source assembly for enriched daily snapshots.

This module is intentionally limited to data acquisition/normalization and
snapshot assembly.  It does not score TDT-RM signals and does not modify TCWRS,
ETI-5, Crash Probability, Bear Trend Filter, CAL, or decision-matrix logic.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field, fields
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .daily_runner import DailyDataFetcher
from .daily_snapshot import (
    DailyMarketSnapshot,
    DailySnapshotValidationResult,
    validate_daily_snapshot,
)
from .eti5 import ETI5Input
from .market_data import MarketPriceBar, derive_price_features
from .tcwrs import TCWRSInput

SourceRow = Mapping[str, Any]

_MANUAL_SOURCE_KINDS = {"manual", "formal"}
_PRICE_FIELDS = {
    "observed_at",
    "close",
    "ma5",
    "ma20",
    "ma60",
    "ma20_slope",
    "one_day_return_pct",
    "two_day_return_pct",
    "turnover_amount",
    "ma20_turnover",
}
_TCWRS_FIELDS = {item.name for item in fields(TCWRSInput)}
_ETI5_FIELDS = {item.name for item in fields(ETI5Input)}
_EXTRA_PROVIDER_FIELDS = {"usd_twd", "main_7_symbols", "main_7_below_ma20_symbols"}
_CANONICAL_FIELDS = _TCWRS_FIELDS | _ETI5_FIELDS | _EXTRA_PROVIDER_FIELDS | {"observed_at", "tail_risk", "bcd", "mhs", "return_60d_pct", "previous_ma60"}
_DEFAULT_ALIASES: dict[str, tuple[str, ...]] = {
    "observed_at": ("observed_at", "trade_date", "date", "日期", "資料日期"),
    "close": ("close", "taiex_close", "index_close", "收盤價", "closing_index"),
    "ma5": ("ma5", "taiex_ma5", "index_ma5"),
    "ma20": ("ma20", "taiex_ma20", "index_ma20"),
    "ma60": ("ma60", "taiex_ma60", "index_ma60"),
    "ma20_slope": ("ma20_slope", "taiex_ma20_slope", "index_ma20_slope"),
    "tail_risk": ("tail_risk", "tail_risk_score", "formal_tail_risk"),
    "bcd": ("bcd", "bcd_score", "formal_bcd"),
    "mhs": ("mhs", "mhs_score"),
    "foreign_spot_net_sell_consecutive_days": ("foreign_spot_net_sell_consecutive_days",),
    "foreign_large_sell": ("foreign_large_sell",),
    "futures_hedging_increases": ("futures_hedging_increases", "futures_hedging_significant"),
    "usd_twd_3d_change_pct": ("usd_twd_3d_change_pct", "usdtwd_3d_change_pct"),
    "usd_twd_5d_change_pct": ("usd_twd_5d_change_pct", "usdtwd_5d_change_pct"),
    "index_down": ("index_down",),
    "declining_issues_significantly_gt_advancing": ("declining_issues_significantly_gt_advancing",),
    "breadth_weakens_for_2_days": ("breadth_weakens_for_2_days",),
    "count_main_7_below_ma20": ("count_main_7_below_ma20",),
}
_BOOL_FIELDS = {
    item.name for item in fields(TCWRSInput) if item.type in {bool, "bool"}
} | {item.name for item in fields(ETI5Input) if item.type in {bool, "bool"}}
_INT_FIELDS = {
    "foreign_spot_net_sell_consecutive_days",
    "close_below_ma20_consecutive_days",
    "advancing_issues",
    "declining_issues",
    "declining_gt_advancing_consecutive_days",
    "count_main_7_below_ma20",
    "count_main_7_below_ma60",
}
_CATEGORY_FIELDS: dict[str, tuple[str, ...]] = {
    "price": tuple(sorted(_PRICE_FIELDS)),
    "foreign_flow": ("foreign_spot_net_buy", "foreign_spot_net_sell", "foreign_spot_net_sell_consecutive_days", "foreign_large_sell", "foreign_spot_large_sell", "futures_hedging_increases", "futures_hedging_significant"),
    "fx": ("usd_twd_3d_change_pct", "usd_twd_5d_change_pct", "twd_appreciates", "twd_stable", "twd_depreciates_significantly"),
    "breadth": ("index_down", "advancing_issues", "declining_issues", "declining_issues_significantly_expand", "declining_issues_significantly_gt_advancing", "declining_gt_advancing_consecutive_days", "breadth_weakens_for_2_days", "count_main_7_below_ma20", "count_main_7_below_ma60"),
    "leadership": ("count_main_7_below_ma20", "count_main_7_below_ma60", "majority_main_7_assets_above_ma20", "main_7_symbols", "main_7_below_ma20_symbols"),
    "margin": ("margin_balance_5d_flat_or_down", "hot_stock_margin_fast_increase", "margin_balance_5d_increases", "index_5d_return_pct", "margin_balance_5d_decline_pct", "margin_not_retreating"),
    "scores": ("tail_risk", "bcd", "mhs"),
}


@dataclass(frozen=True)
class DailyProviderCapability:
    """Declared source coverage for one provider category."""

    category: str
    canonical_fields: tuple[str, ...] = ()
    source_kind: str = "auto"
    precedence: int | None = None
    notes: str | None = None

    @property
    def effective_precedence(self) -> int:
        if self.precedence is not None:
            return self.precedence
        return _source_kind_precedence(self.source_kind)


@dataclass(frozen=True)
class DailyProviderContext:
    """Runtime context shared with all daily source providers."""

    as_of: date
    field_map: Mapping[str, str] = field(default_factory=dict)
    provider_field_maps: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def field_map_for(self, provider_id: str, category: str | None = None) -> Mapping[str, str]:
        maps: dict[str, str] = {}
        maps.update(_normalize_field_map(self.field_map))
        for key in (category or "", provider_id):
            scoped = self.provider_field_maps.get(key)
            if scoped:
                maps.update(_normalize_field_map(scoped))
        return maps


@dataclass(frozen=True)
class DailyProviderResult:
    """Canonical fields and provenance emitted by one provider."""

    provider_id: str
    provider_name: str
    canonical_fields: Mapping[str, Any] = field(default_factory=dict)
    capabilities: tuple[DailyProviderCapability, ...] = ()
    price_bars: tuple[MarketPriceBar, ...] = ()
    source_metadata: Mapping[str, Any] = field(default_factory=dict)
    field_sources: Mapping[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    retrieved_at: str | None = None

    @property
    def source_kind(self) -> str:
        for capability in self.capabilities:
            if capability.source_kind:
                return capability.source_kind
        return "auto"

    @property
    def precedence(self) -> int:
        if not self.capabilities:
            return _source_kind_precedence("auto")
        return max(capability.effective_precedence for capability in self.capabilities)


class DailySourceProvider(Protocol):
    """Protocol for local/public daily snapshot source adapters."""

    provider_id: str
    provider_name: str
    capabilities: tuple[DailyProviderCapability, ...]

    def fetch_or_load(self, context: DailyProviderContext) -> DailyProviderResult:
        """Return canonical fields for ``context.as_of`` or provider errors."""


@dataclass
class DailyProviderRegistry:
    """Simple auditable registry of daily source providers."""

    providers: dict[str, DailySourceProvider] = field(default_factory=dict)

    def register(self, provider: DailySourceProvider) -> None:
        if provider.provider_id in self.providers:
            raise ValueError(f"daily provider already registered: {provider.provider_id}")
        self.providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> DailySourceProvider:
        return self.providers[provider_id]

    def list(self) -> tuple[DailySourceProvider, ...]:
        return tuple(self.providers.values())


@dataclass(frozen=True)
class DailySnapshotAssemblyResult:
    """Assembler output plus validation and audit details."""

    snapshot: DailyMarketSnapshot
    validation: DailySnapshotValidationResult
    provider_results: tuple[DailyProviderResult, ...] = ()
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    provider_errors: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    missing_field_categories: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return self.validation.is_valid and not self.provider_errors


@dataclass(frozen=True)
class StaticMappingProvider:
    """Provider that emits canonical fields from an in-memory mapping."""

    provider_id: str
    provider_name: str
    mapping: Mapping[str, Any]
    category: str = "manual"
    source_kind: str = "manual"
    capabilities: tuple[DailyProviderCapability, ...] = ()

    def __post_init__(self) -> None:
        if not self.capabilities:
            object.__setattr__(
                self,
                "capabilities",
                (DailyProviderCapability(self.category, tuple(self.mapping), self.source_kind),),
            )

    def fetch_or_load(self, context: DailyProviderContext) -> DailyProviderResult:
        canonical = _canonicalize_row(self.mapping, field_map=context.field_map_for(self.provider_id, self.category))
        return _provider_result(self, canonical, notes="In-memory static mapping")


@dataclass(frozen=True)
class LocalCsvProvider:
    """Provider for one-row or date-filtered local CSV source rows."""

    provider_id: str
    provider_name: str
    path: str | Path
    category: str
    field_map: Mapping[str, str] = field(default_factory=dict)
    source_kind: str = "auto"
    date_field: str = "observed_at"
    capabilities: tuple[DailyProviderCapability, ...] = ()

    def __post_init__(self) -> None:
        if not self.capabilities:
            fields_for_category = tuple(self.field_map) or _CATEGORY_FIELDS.get(self.category, ())
            object.__setattr__(
                self,
                "capabilities",
                (DailyProviderCapability(self.category, fields_for_category, self.source_kind),),
            )

    def fetch_or_load(self, context: DailyProviderContext) -> DailyProviderResult:
        try:
            with Path(self.path).open(newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
        except OSError as exc:
            return _provider_result(self, {}, errors=(f"{self.provider_id}: cannot read CSV {self.path}: {exc}",))
        row = _select_row(rows, context.as_of, self.date_field)
        if row is None:
            return _provider_result(self, {}, errors=(f"{self.provider_id}: no CSV row found for {context.as_of.isoformat()}",))
        field_map = dict(context.field_map_for(self.provider_id, self.category))
        field_map.update(self.field_map)
        canonical = _canonicalize_row(row, field_map=field_map)
        return _provider_result(self, canonical, notes=str(self.path))


@dataclass(frozen=True)
class LocalJsonProvider:
    """Provider for a local JSON object or date-filtered list of objects."""

    provider_id: str
    provider_name: str
    path: str | Path
    category: str
    field_map: Mapping[str, str] = field(default_factory=dict)
    source_kind: str = "auto"
    date_field: str = "observed_at"
    capabilities: tuple[DailyProviderCapability, ...] = ()

    def __post_init__(self) -> None:
        if not self.capabilities:
            fields_for_category = tuple(self.field_map) or _CATEGORY_FIELDS.get(self.category, ())
            object.__setattr__(
                self,
                "capabilities",
                (DailyProviderCapability(self.category, fields_for_category, self.source_kind),),
            )

    def fetch_or_load(self, context: DailyProviderContext) -> DailyProviderResult:
        try:
            payload = json.loads(Path(self.path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return _provider_result(self, {}, errors=(f"{self.provider_id}: cannot read JSON {self.path}: {exc}",))
        if isinstance(payload, Mapping) and isinstance(payload.get("canonical_row"), Mapping):
            row: Mapping[str, Any] | None = payload["canonical_row"]  # type: ignore[index]
        elif isinstance(payload, Mapping):
            row = payload
        elif isinstance(payload, list):
            row = _select_row([item for item in payload if isinstance(item, Mapping)], context.as_of, self.date_field)
        else:
            row = None
        if row is None:
            return _provider_result(self, {}, errors=(f"{self.provider_id}: no JSON row found for {context.as_of.isoformat()}",))
        field_map = dict(context.field_map_for(self.provider_id, self.category))
        field_map.update(self.field_map)
        canonical = _canonicalize_row(row, field_map=field_map)
        return _provider_result(self, canonical, notes=str(self.path))


@dataclass(frozen=True)
class TAIEXPriceProvider:
    """TAIEX price provider using existing price-bar feature derivation helpers."""

    provider_id: str = "taiex_price"
    provider_name: str = "TAIEX price provider"
    source_path: str | Path | None = None
    fetcher: DailyDataFetcher | None = None
    min_bars: int = 61
    source_kind: str = "price"
    capabilities: tuple[DailyProviderCapability, ...] = (
        DailyProviderCapability("price", tuple(sorted(_PRICE_FIELDS)), "price", 80),
    )

    def fetch_or_load(self, context: DailyProviderContext) -> DailyProviderResult:
        try:
            bars = _load_price_bars(self.source_path, context) if self.source_path else tuple(self.fetcher.fetch_bars(as_of=context.as_of, min_bars=self.min_bars)) if self.fetcher else ()
            if bars:
                ordered = tuple(sorted(bars, key=lambda bar: _coerce_date(bar.observed_at)))
                if len(ordered) >= 60:
                    features = derive_price_features(ordered)
                    return _provider_result(self, features, price_bars=ordered, notes=str(self.source_path or "fetcher"))
            # Allow one-row CSVs with already-derived canonical price fields.
            if self.source_path:
                csv_result = LocalCsvProvider(
                    self.provider_id,
                    self.provider_name,
                    self.source_path,
                    "price",
                    source_kind="price",
                    capabilities=self.capabilities,
                ).fetch_or_load(context)
                if csv_result.canonical_fields:
                    return csv_result
            return _provider_result(self, {}, errors=(f"{self.provider_id}: no usable price bars or price fields",))
        except Exception as exc:  # noqa: BLE001 - provider errors must be collected, not raised.
            return _provider_result(self, {}, errors=(f"{self.provider_id}: {exc}",))


@dataclass(frozen=True)
class ManualScoreProvider:
    """Provider for formal/manual Tail Risk, BCD, and optional MHS values."""

    provider_id: str
    provider_name: str
    row: Mapping[str, Any]
    field_map: Mapping[str, str] = field(default_factory=dict)
    capabilities: tuple[DailyProviderCapability, ...] = (
        DailyProviderCapability("scores", ("tail_risk", "bcd", "mhs"), "formal", 100),
    )

    def fetch_or_load(self, context: DailyProviderContext) -> DailyProviderResult:
        field_map = dict(context.field_map_for(self.provider_id, "scores"))
        field_map.update(self.field_map)
        canonical = {key: value for key, value in _canonicalize_row(self.row, field_map=field_map).items() if key in {"observed_at", "tail_risk", "bcd", "mhs"}}
        return _provider_result(self, canonical, notes="Manual/formal score row")


@dataclass(frozen=True)
class DailySnapshotAssembler:
    """Merge daily provider outputs into a validated ``DailyMarketSnapshot``."""

    providers: Sequence[DailySourceProvider]
    data_status: str = "enriched_snapshot"
    precedence_rules: Mapping[str, int] = field(default_factory=dict)

    def assemble(self, context: DailyProviderContext) -> DailySnapshotAssemblyResult:
        canonical_row: dict[str, Any] = {"observed_at": context.as_of.isoformat()}
        field_sources: dict[str, str] = {"observed_at": "assembly_context"}
        source_metadata: dict[str, dict[str, Any]] = {
            "assembly_context": {"name": "Assembler context", "retrieved_at": _utc_now(), "notes": "--as-of value"}
        }
        provider_results: list[DailyProviderResult] = []
        warnings: list[str] = []
        limitations: list[str] = []
        provider_errors: list[str] = []
        conflicts: list[str] = []
        priorities: dict[str, int] = {"observed_at": 0}
        price_bars: tuple[MarketPriceBar, ...] = ()

        for provider in self.providers:
            result = provider.fetch_or_load(context)
            provider_results.append(result)
            warnings.extend(result.warnings)
            limitations.extend(result.limitations)
            provider_errors.extend(result.errors)
            source_metadata[result.provider_id] = _metadata_for_result(result)
            if result.price_bars:
                price_bars = result.price_bars
            for field_name, value in result.canonical_fields.items():
                if _missing(value):
                    continue
                priority = self.precedence_rules.get(field_name, result.precedence)
                if field_name in canonical_row and not _same_value(canonical_row[field_name], value):
                    previous_source = field_sources.get(field_name, "unknown")
                    previous_priority = priorities.get(field_name, 0)
                    conflict = (
                        f"field conflict for {field_name}: kept/updated between {previous_source}="
                        f"{canonical_row[field_name]!r} and {result.provider_id}={value!r}"
                    )
                    conflicts.append(conflict)
                    if priority > previous_priority:
                        warnings.append(f"{conflict}; {result.provider_id} won by precedence rule")
                        canonical_row[field_name] = value
                        field_sources[field_name] = result.field_sources.get(field_name, result.provider_id)
                        priorities[field_name] = priority
                    else:
                        warnings.append(f"{conflict}; kept {previous_source} by precedence rule")
                    continue
                canonical_row[field_name] = value
                field_sources[field_name] = result.field_sources.get(field_name, result.provider_id)
                priorities[field_name] = priority

        trade_date = _coerce_date(canonical_row.get("observed_at") or context.as_of)
        snapshot = DailyMarketSnapshot(
            trade_date=trade_date,
            observed_at=trade_date,
            canonical_row=canonical_row,
            price_bars=price_bars,
            field_sources=field_sources,
            source_metadata=source_metadata,
            data_status=self.data_status,
            limitations=tuple(dict.fromkeys(limitations)),
            warnings=tuple(dict.fromkeys(warnings)),
        )
        validation = validate_daily_snapshot(snapshot, as_of=context.as_of)
        missing_categories = _missing_categories(snapshot.canonical_row)
        return DailySnapshotAssemblyResult(
            snapshot=snapshot,
            validation=validation,
            provider_results=tuple(provider_results),
            warnings=snapshot.warnings,
            limitations=snapshot.limitations,
            provider_errors=tuple(provider_errors),
            conflicts=tuple(conflicts),
            missing_field_categories=missing_categories,
        )


def _provider_result(
    provider: Any,
    canonical: Mapping[str, Any],
    *,
    price_bars: Sequence[MarketPriceBar] = (),
    notes: str | None = None,
    errors: tuple[str, ...] = (),
) -> DailyProviderResult:
    retrieved_at = _utc_now()
    metadata = {"name": provider.provider_name, "retrieved_at": retrieved_at, "category": getattr(provider, "category", None), "notes": notes}
    return DailyProviderResult(
        provider_id=provider.provider_id,
        provider_name=provider.provider_name,
        canonical_fields=canonical,
        capabilities=tuple(provider.capabilities),
        price_bars=tuple(price_bars),
        source_metadata=metadata,
        field_sources={key: provider.provider_id for key in canonical},
        errors=errors,
        retrieved_at=retrieved_at,
    )


def _metadata_for_result(result: DailyProviderResult) -> dict[str, Any]:
    metadata = dict(result.source_metadata)
    metadata.setdefault("name", result.provider_name)
    metadata.setdefault("retrieved_at", result.retrieved_at)
    metadata["capabilities"] = [
        {
            "category": item.category,
            "canonical_fields": list(item.canonical_fields),
            "source_kind": item.source_kind,
            "precedence": item.effective_precedence,
            "notes": item.notes,
        }
        for item in result.capabilities
    ]
    return metadata


def _canonicalize_row(row: Mapping[str, Any], *, field_map: Mapping[str, str] | None = None) -> dict[str, Any]:
    canonical: dict[str, Any] = {}
    field_map = _normalize_field_map(field_map or {})
    claimed_raw_keys = set(field_map.values()) if field_map else set()
    if field_map:
        for canonical_name, raw_name in field_map.items():
            if raw_name in row and not _missing(row[raw_name]):
                canonical[canonical_name] = _coerce_value(canonical_name, row[raw_name])
    for canonical_name in _CANONICAL_FIELDS:
        if canonical_name in canonical:
            continue
        for raw_name in (canonical_name, *_DEFAULT_ALIASES.get(canonical_name, ())):
            if raw_name in row and raw_name not in claimed_raw_keys and not _missing(row[raw_name]):
                canonical[canonical_name] = _coerce_value(canonical_name, row[raw_name])
                break
    return canonical


def _normalize_field_map(field_map: Mapping[str, str]) -> dict[str, str]:
    """Return canonical-field to raw-column mappings.

    Field-map fixtures historically used canonical-to-raw mappings, while some
    provider samples are easier to read as raw-to-canonical mappings.  Accept
    both forms deterministically: if the key is canonical it is kept as-is; if
    the value is canonical, the pair is inverted.
    """

    normalized: dict[str, str] = {}
    for left, right in field_map.items():
        canonical_left = left in _CANONICAL_FIELDS
        canonical_right = right in _CANONICAL_FIELDS
        if canonical_left or not canonical_right:
            normalized[str(left)] = str(right)
        else:
            normalized[str(right)] = str(left)
    return normalized


def _select_row(rows: Sequence[Mapping[str, Any]], as_of: date, date_field: str) -> Mapping[str, Any] | None:
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    matches: list[Mapping[str, Any]] = []
    for row in rows:
        for key in (date_field, "observed_at", "trade_date", "date"):
            if key in row and not _missing(row[key]) and _coerce_date(row[key]) == as_of:
                matches.append(row)
                break
    return matches[-1] if matches else None


def _load_price_bars(path: str | Path | None, context: DailyProviderContext) -> tuple[MarketPriceBar, ...]:
    if path is None:
        return ()
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    bars: list[MarketPriceBar] = []
    for row in rows:
        mapped = _canonicalize_row(row, field_map=context.field_map_for("taiex_price", "price"))
        if "close" not in mapped:
            return ()
        observed_at = mapped.get("observed_at") or row.get("date") or row.get("trade_date")
        if observed_at is None:
            return ()
        bar_date = _coerce_date(observed_at)
        if bar_date <= context.as_of:
            bars.append(
                MarketPriceBar(
                    observed_at=bar_date,
                    close=float(mapped["close"]),
                    turnover_amount=float(mapped.get("turnover_amount") or row.get("turnover_amount") or row.get("turnover") or 0.0),
                    open=_optional_float(row.get("open")),
                    high=_optional_float(row.get("high")),
                    low=_optional_float(row.get("low")),
                    volume=_optional_float(row.get("volume")),
                )
            )
    return tuple(sorted(bars, key=lambda bar: _coerce_date(bar.observed_at)))


def _missing_categories(row: Mapping[str, Any]) -> tuple[str, ...]:
    missing = []
    for category, names in _CATEGORY_FIELDS.items():
        if not any(not _missing(row.get(name)) for name in names):
            missing.append(category)
    return tuple(missing)


def _source_kind_precedence(source_kind: str) -> int:
    if source_kind in _MANUAL_SOURCE_KINDS:
        return 100
    if source_kind == "price":
        return 80
    if source_kind == "proxy":
        return 10
    return 50


def _coerce_value(name: str, value: Any) -> Any:
    if name in _BOOL_FIELDS:
        return _coerce_bool(value)
    if name in _INT_FIELDS:
        return int(float(value))
    if name in (_TCWRS_FIELDS | _ETI5_FIELDS | {"tail_risk", "bcd", "mhs", "return_60d_pct", "previous_ma60"}) and name != "observed_at":
        if isinstance(value, str):
            stripped = value.replace(",", "").strip()
            if stripped == "":
                return value
            try:
                return float(stripped)
            except ValueError:
                return value
    return value


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on", "是"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off", "否", ""}:
        return False
    raise ValueError(f"cannot coerce {value!r} to bool")


def _coerce_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            pass
    return date.fromisoformat(text[:10])


def _optional_float(value: Any) -> float | None:
    if _missing(value):
        return None
    return float(str(value).replace(",", ""))


def _missing(value: Any) -> bool:
    return value is None or value == ""


def _same_value(left: Any, right: Any) -> bool:
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return str(left) == str(right)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
