"""Daily enriched market snapshot bridge for TDT-RM production runs.

The snapshot layer is vendor-neutral: it normalizes local JSON/CSV rows into the
same canonical market-data fields already accepted by :mod:`tdt_rm.market_data`,
tracks source coverage, and deliberately leaves model scoring logic unchanged.
"""

from __future__ import annotations

import csv
import json
from dataclasses import MISSING, dataclass, field, fields
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .eti5 import ETI5Input
from .market_data import MarketDataObservation, MarketPriceBar, ingest_market_data_row
from .tcwrs import TCWRSInput

SNAPSHOT_ERROR_SEVERITY = "error"
SNAPSHOT_WARNING_SEVERITY = "warning"

_TCWRS_REQUIRED_FIELDS = {
    item.name for item in fields(TCWRSInput) if item.default is MISSING and item.default_factory is MISSING
}
_REQUIRED_CANONICAL_FIELDS = {"observed_at", *_TCWRS_REQUIRED_FIELDS}

_ALIASES: dict[str, tuple[str, ...]] = {
    "observed_at": ("observed_at", "trade_date", "date", "資料日期"),
    "close": ("close", "taiex_close", "index_close", "收盤價"),
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
    "breadth_history": ("breadth_history", "advancing_declining_history"),
    "main7_returns": ("main7_returns", "main_7_returns"),
    "main7_weights": ("main7_weights", "main_7_weights"),
    "sector_returns": ("sector_returns",),
    "sector_above_ma20": ("sector_above_ma20",),
    "otc_return_pct": ("otc_return_pct",),
    "small_mid_advancing_issues": ("small_mid_advancing_issues",),
    "small_mid_declining_issues": ("small_mid_declining_issues",),
    "small_mid_return_pct": ("small_mid_return_pct",),
    "turnover_concentration_topn": ("turnover_concentration_topn", "topn_turnover_concentration"),
}

_ETI_COMPONENT_FIELDS: dict[str, tuple[str, ...]] = {
    "ETI-1": ("close", "ma20"),
    "ETI-2": (
        "foreign_spot_net_sell_consecutive_days",
        "foreign_large_sell",
        "futures_hedging_increases",
        "foreign_spot_large_sell",
        "futures_hedging_significant",
    ),
    "ETI-3": ("usd_twd_3d_change_pct", "usd_twd_5d_change_pct"),
    "ETI-4": (
        "index_down",
        "declining_issues_significantly_gt_advancing",
        "breadth_weakens_for_2_days",
        "advancing_issues",
        "declining_issues",
    ),
    "ETI-5": ("count_main_7_below_ma20",),
}


@dataclass(frozen=True)
class DailyFieldSource:
    """Source attribution for one canonical field."""

    field: str
    source_id: str
    source_name: str | None = None
    retrieved_at: str | None = None
    notes: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "retrieved_at": self.retrieved_at,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class DailySourceCoverage:
    """Coverage summary for an enriched daily snapshot."""

    field_sources: Mapping[str, DailyFieldSource] = field(default_factory=dict)
    source_metadata: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    missing_fields: tuple[str, ...] = ()
    available_eti_components: tuple[str, ...] = ()
    data_status: str = "enriched_snapshot"
    limitations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "field_sources": {key: value.as_dict() for key, value in self.field_sources.items()},
            "source_metadata": {key: dict(value) for key, value in self.source_metadata.items()},
            "missing_fields": list(self.missing_fields),
            "available_eti_components": list(self.available_eti_components),
            "data_status": self.data_status,
            "limitations": list(self.limitations),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class DailyMarketSnapshot:
    """Canonical one-day market snapshot with optional price history and provenance."""

    trade_date: date
    observed_at: datetime | date | None = None
    canonical_row: Mapping[str, Any] = field(default_factory=dict)
    price_bars: tuple[MarketPriceBar, ...] = ()
    field_sources: Mapping[str, str] = field(default_factory=dict)
    source_metadata: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    data_status: str = "enriched_snapshot"
    limitations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date.isoformat(),
            "observed_at": _date_or_datetime_iso(self.observed_at or self.trade_date),
            "canonical_row": dict(self.canonical_row),
            "price_bars": [_price_bar_as_dict(bar) for bar in self.price_bars],
            "field_sources": dict(self.field_sources),
            "source_metadata": {key: dict(value) for key, value in self.source_metadata.items()},
            "data_status": self.data_status,
            "limitations": list(self.limitations),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class DailySnapshotValidationIssue:
    """One validation issue found in a daily snapshot."""

    severity: str
    code: str
    message: str
    field: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"severity": self.severity, "code": self.code, "message": self.message, "field": self.field}


@dataclass(frozen=True)
class DailySnapshotValidationResult:
    """Validation summary for a daily snapshot."""

    issues: tuple[DailySnapshotValidationIssue, ...] = ()
    coverage: DailySourceCoverage | None = None

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == SNAPSHOT_ERROR_SEVERITY for issue in self.issues)

    def as_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "issues": [issue.as_dict() for issue in self.issues],
            "coverage": self.coverage.as_dict() if self.coverage else None,
        }


def load_daily_snapshot_json(path: str | Path) -> DailyMarketSnapshot:
    """Load a normalized daily market snapshot JSON file."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("daily snapshot JSON root must be an object")
    return _snapshot_from_mapping(payload)


def load_daily_snapshot_csv(path: str | Path, *, field_map: Mapping[str, str] | None = None) -> DailyMarketSnapshot:
    """Load one daily canonical row from CSV into a daily market snapshot."""

    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1:
        raise ValueError(f"daily snapshot CSV must contain exactly one data row; found {len(rows)}")
    canonical_row = _canonicalize_row(rows[0], field_map=field_map)
    trade_date = _coerce_date(canonical_row.get("observed_at") or canonical_row.get("trade_date"))
    canonical_row.setdefault("observed_at", trade_date.isoformat())
    source_id = "input_csv"
    return DailyMarketSnapshot(
        trade_date=trade_date,
        observed_at=trade_date,
        canonical_row=canonical_row,
        field_sources={key: source_id for key in canonical_row},
        source_metadata={source_id: {"name": "Local CSV input", "notes": str(path)}},
        data_status="enriched_snapshot",
    )


def validate_daily_snapshot(snapshot: DailyMarketSnapshot, *, as_of: date | None = None) -> DailySnapshotValidationResult:
    """Validate snapshot shape and required canonical market-data fields."""

    issues: list[DailySnapshotValidationIssue] = []
    row = dict(snapshot.canonical_row)
    missing = sorted(field for field in _REQUIRED_CANONICAL_FIELDS if _missing(row.get(field)))
    for field_name in missing:
        issues.append(_issue(SNAPSHOT_ERROR_SEVERITY, "missing_required_field", f"canonical_row.{field_name} is required", f"canonical_row.{field_name}"))
    if as_of is not None and snapshot.trade_date > as_of:
        issues.append(_issue(SNAPSHOT_ERROR_SEVERITY, "future_trade_date", f"snapshot trade_date {snapshot.trade_date} is after as_of {as_of}", "trade_date"))
    if snapshot.price_bars:
        dates = [_coerce_date(bar.observed_at) for bar in snapshot.price_bars]
        if dates != sorted(dates):
            issues.append(_issue(SNAPSHOT_ERROR_SEVERITY, "price_bars_not_chronological", "price_bars must be chronological", "price_bars"))
        if dates[-1] != snapshot.trade_date:
            issues.append(_issue(SNAPSHOT_WARNING_SEVERITY, "price_bars_trade_date_mismatch", "latest price bar date does not match trade_date", "price_bars"))
    coverage = build_source_coverage(snapshot)
    unavailable = sorted(set(_ETI_COMPONENT_FIELDS) - set(coverage.available_eti_components))
    if unavailable:
        issues.append(_issue(SNAPSHOT_WARNING_SEVERITY, "eti_components_unavailable", f"ETI components unavailable from source fields: {', '.join(unavailable)}", "canonical_row"))
    try:
        snapshot_to_market_observation(snapshot)
    except ValueError as exc:
        issues.append(_issue(SNAPSHOT_ERROR_SEVERITY, "market_data_ingestion_failed", str(exc), "canonical_row"))
    return DailySnapshotValidationResult(tuple(issues), coverage)


def snapshot_to_market_observation(snapshot: DailyMarketSnapshot) -> MarketDataObservation:
    """Convert a snapshot canonical row into the MarketDataObservation bridge type."""

    row = dict(snapshot.canonical_row)
    row.setdefault("observed_at", snapshot.trade_date.isoformat())
    metadata = {
        "snapshot_trade_date": snapshot.trade_date.isoformat(),
        "data_status": snapshot.data_status,
        "field_sources": dict(snapshot.field_sources),
        "source_metadata": {key: dict(value) for key, value in snapshot.source_metadata.items()},
    }
    return ingest_market_data_row(row, metadata=metadata)


def derive_eti_available_components(snapshot: DailyMarketSnapshot) -> set[str]:
    """Derive ETI-5 component availability only from supplied source fields."""

    row = dict(snapshot.canonical_row)
    supplied_fields = {field for field, source_id in snapshot.field_sources.items() if source_id}
    supplied_row = {field: value for field, value in row.items() if field in supplied_fields}
    available: set[str] = set()
    if _has_all(supplied_row, ("close", "ma20")):
        available.add("ETI-1")
    if _has_any(supplied_row, _ETI_COMPONENT_FIELDS["ETI-2"]):
        available.add("ETI-2")
    if _has_any(supplied_row, _ETI_COMPONENT_FIELDS["ETI-3"]):
        available.add("ETI-3")
    if _has_any(supplied_row, _ETI_COMPONENT_FIELDS["ETI-4"]):
        available.add("ETI-4")
    if _has_any(supplied_row, _ETI_COMPONENT_FIELDS["ETI-5"]):
        available.add("ETI-5")
    return available


def build_source_coverage(snapshot: DailyMarketSnapshot) -> DailySourceCoverage:
    """Build source coverage, missing-field, and ETI availability metadata."""

    row = dict(snapshot.canonical_row)
    field_sources: dict[str, DailyFieldSource] = {}
    for field_name, source_id in snapshot.field_sources.items():
        metadata = dict(snapshot.source_metadata.get(source_id, {}))
        field_sources[field_name] = DailyFieldSource(
            field=field_name,
            source_id=source_id,
            source_name=metadata.get("name") or metadata.get("source_name"),
            retrieved_at=metadata.get("retrieved_at"),
            notes=metadata.get("notes"),
        )
    missing = sorted(field_name for field_name in _REQUIRED_CANONICAL_FIELDS if _missing(row.get(field_name)))
    return DailySourceCoverage(
        field_sources=field_sources,
        source_metadata=snapshot.source_metadata,
        missing_fields=tuple(missing),
        available_eti_components=tuple(sorted(derive_eti_available_components(snapshot))),
        data_status=snapshot.data_status,
        limitations=tuple(snapshot.limitations),
        warnings=tuple(snapshot.warnings),
    )


def _snapshot_from_mapping(payload: Mapping[str, Any]) -> DailyMarketSnapshot:
    row = payload.get("canonical_row")
    if row is None:
        row = {key: value for key, value in payload.items() if key not in {"price_bars", "field_sources", "source_metadata", "data_status", "limitations", "warnings"}}
    if not isinstance(row, Mapping):
        raise ValueError("daily snapshot canonical_row must be an object")
    trade_date = _coerce_date(payload.get("trade_date") or row.get("trade_date") or row.get("observed_at"))
    canonical_row = dict(row)
    canonical_row.setdefault("observed_at", trade_date.isoformat())
    bars = tuple(_price_bar_from_mapping(item) for item in payload.get("price_bars", ()) or ())
    return DailyMarketSnapshot(
        trade_date=trade_date,
        observed_at=_coerce_observed_at(payload.get("observed_at") or canonical_row.get("observed_at") or trade_date),
        canonical_row=canonical_row,
        price_bars=bars,
        field_sources=dict(payload.get("field_sources", {}) or {}),
        source_metadata={key: dict(value) for key, value in dict(payload.get("source_metadata", {}) or {}).items()},
        data_status=str(payload.get("data_status") or "enriched_snapshot"),
        limitations=tuple(str(item) for item in payload.get("limitations", ()) or ()),
        warnings=tuple(str(item) for item in payload.get("warnings", ()) or ()),
    )


def _canonicalize_row(row: Mapping[str, Any], *, field_map: Mapping[str, str] | None) -> dict[str, Any]:
    canonical: dict[str, Any] = {}
    claimed_raw_keys = set(field_map.values()) if field_map else set()
    if field_map:
        for canonical_name, raw_name in field_map.items():
            if raw_name in row and not _missing(row[raw_name]):
                canonical[canonical_name] = row[raw_name]
    candidates = set(_ALIASES) | {field.name for field in fields(TCWRSInput)} | {field.name for field in fields(ETI5Input)} | {"tail_risk", "bcd", "mhs", "observed_at"}
    for canonical_name in candidates:
        if canonical_name in canonical:
            continue
        for raw_name in (canonical_name, *_ALIASES.get(canonical_name, ())):
            if raw_name in row and raw_name not in claimed_raw_keys and not _missing(row[raw_name]):
                canonical[canonical_name] = row[raw_name]
                break
    return canonical


def _price_bar_from_mapping(row: Mapping[str, Any]) -> MarketPriceBar:
    return MarketPriceBar(
        observed_at=_coerce_date(row.get("observed_at") or row.get("date") or row.get("trade_date")),
        close=float(row["close"]),
        turnover_amount=float(row.get("turnover_amount") or row.get("turnover") or 0.0),
        open=_optional_float(row.get("open")),
        high=_optional_float(row.get("high")),
        low=_optional_float(row.get("low")),
        volume=_optional_float(row.get("volume")),
    )


def _price_bar_as_dict(bar: MarketPriceBar) -> dict[str, Any]:
    return {
        "observed_at": _coerce_date(bar.observed_at).isoformat(),
        "close": bar.close,
        "turnover_amount": bar.turnover_amount,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "volume": bar.volume,
    }


def _issue(severity: str, code: str, message: str, field_name: str | None = None) -> DailySnapshotValidationIssue:
    return DailySnapshotValidationIssue(severity=severity, code=code, message=message, field=field_name)


def _has_all(row: Mapping[str, Any], names: Sequence[str]) -> bool:
    return all(not _missing(row.get(name)) for name in names)


def _has_any(row: Mapping[str, Any], names: Sequence[str]) -> bool:
    return any(not _missing(row.get(name)) for name in names)


def _missing(value: Any) -> bool:
    return value is None or value == ""


def _optional_float(value: Any) -> float | None:
    if _missing(value):
        return None
    return float(value)


def _coerce_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        raise ValueError("snapshot is missing trade_date/observed_at")
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            pass
    return date.fromisoformat(text[:10])


def _coerce_observed_at(value: Any) -> datetime | date:
    if isinstance(value, (datetime, date)):
        return value
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return _coerce_date(text)


def _date_or_datetime_iso(value: datetime | date) -> str:
    return value.isoformat()
