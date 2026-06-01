"""Market data ingestion helpers for TDT-RM scoring modules.

The ingestion layer is intentionally dependency-free and vendor-neutral.  It
normalizes raw mapping/CSV rows into canonical ``TCWRSInput`` and ``ETI5Input``
objects, records data-completeness status, and can bridge directly into the
historical backtest framework.
"""

from __future__ import annotations

import csv
from dataclasses import MISSING, dataclass, field, fields
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .backtest import HistoricalBacktestObservation
from .eti5 import ETI5Input
from .tcwrs import TCWRSInput

TraceOutput = dict[str, Any]
RawRow = Mapping[str, Any]
FieldMap = Mapping[str, str]

FORMAL_DATA_STATUS = "正式版"
PROVISIONAL_DATA_STATUS = "暫估版"

_TCWRS_FIELD_NAMES = {field.name for field in fields(TCWRSInput)}
_ETI5_FIELD_NAMES = {field.name for field in fields(ETI5Input)}
_TCWRS_REQUIRED_FIELDS = {
    field.name
    for field in fields(TCWRSInput)
    if field.default is MISSING and field.default_factory is MISSING
}
_ETI5_REQUIRED_FIELDS = {
    field.name
    for field in fields(ETI5Input)
    if field.default is MISSING and field.default_factory is MISSING
}
_NUMERIC_FIELD_NAMES = {
    field.name
    for field in (*fields(TCWRSInput), *fields(ETI5Input))
    if field.type in {float, int} or field.type == "float" or field.type == "int"
}
_BOOL_FIELD_NAMES = {
    field.name
    for field in (*fields(TCWRSInput), *fields(ETI5Input))
    if field.type is bool or field.type == "bool"
}
_INT_FIELD_NAMES = {
    field.name
    for field in (*fields(TCWRSInput), *fields(ETI5Input))
    if field.type is int or field.type == "int"
}

_DEFAULT_ALIASES: dict[str, tuple[str, ...]] = {
    "observed_at": ("observed_at", "date", "trade_date", "資料日期"),
    "close": ("close", "taiex_close", "index_close", "收盤價"),
    "ma5": ("ma5", "taiex_ma5", "index_ma5"),
    "ma20": ("ma20", "taiex_ma20", "index_ma20"),
    "ma60": ("ma60", "taiex_ma60", "index_ma60"),
    "ma20_slope": ("ma20_slope", "taiex_ma20_slope", "index_ma20_slope"),
    "turnover_amount": ("turnover_amount", "taiex_turnover", "turnover"),
    "ma20_turnover": ("ma20_turnover", "turnover_ma20"),
    "advancing_issues": ("advancing_issues", "advancers", "上漲家數"),
    "declining_issues": ("declining_issues", "decliners", "下跌家數"),
    "tail_risk": ("tail_risk", "tail_risk_score"),
    "bcd": ("bcd", "bcd_score"),
    "realized_event": ("realized_event", "event", "crash_event"),
}


@dataclass(frozen=True)
class MarketDataCompleteness:
    """Required-field completeness for one normalized market data row."""

    required_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]
    optional_missing_fields: tuple[str, ...] = ()

    @property
    def is_complete(self) -> bool:
        """Return true when every required field is present."""

        return not self.missing_fields

    @property
    def data_status(self) -> str:
        """Return the spec-compatible formal/provisional data status label."""

        return FORMAL_DATA_STATUS if self.is_complete else PROVISIONAL_DATA_STATUS

    def as_dict(self) -> dict[str, Any]:
        """Return a serializable completeness trace."""

        return {
            "data_status": self.data_status,
            "is_complete": self.is_complete,
            "required_fields": list(self.required_fields),
            "missing_fields": list(self.missing_fields),
            "optional_missing_fields": list(self.optional_missing_fields),
        }


@dataclass(frozen=True)
class MarketPriceBar:
    """Canonical daily price/turnover bar used for derived feature creation."""

    observed_at: date | str
    close: float
    turnover_amount: float = 0.0
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None


@dataclass(frozen=True)
class MarketDataObservation:
    """Normalized market-data row ready for scoring or backtesting."""

    observed_at: date
    tcwrs_input: TCWRSInput
    eti5_input: ETI5Input | None = None
    tail_risk: float | None = None
    bcd: float | None = None
    realized_event: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)
    completeness: MarketDataCompleteness = field(
        default_factory=lambda: MarketDataCompleteness(
            tuple(sorted(_TCWRS_REQUIRED_FIELDS)), ()
        )
    )
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def data_status(self) -> str:
        """Return the formal/provisional data status for this observation."""

        return self.completeness.data_status

    def to_backtest_observation(self) -> HistoricalBacktestObservation:
        """Convert this normalized row into the backtest framework input type."""

        return HistoricalBacktestObservation(
            observed_at=self.observed_at,
            tcwrs_input=self.tcwrs_input,
            eti5_input=self.eti5_input,
            tail_risk=self.tail_risk,
            bcd=self.bcd,
            realized_event=self.realized_event,
            metadata=self.metadata,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a serializable ingestion trace."""

        return {
            "observed_at": self.observed_at.isoformat(),
            "data_status": self.data_status,
            "tcwrs_input": _dataclass_as_dict(self.tcwrs_input),
            "eti5_input": _dataclass_as_dict(self.eti5_input) if self.eti5_input else None,
            "tail_risk": self.tail_risk,
            "bcd": self.bcd,
            "realized_event": self.realized_event,
            "metadata": dict(self.metadata),
            "completeness": self.completeness.as_dict(),
            "raw": dict(self.raw),
        }


def ingest_market_data_row(
    row: RawRow,
    *,
    field_map: FieldMap | None = None,
    require_eti5: bool = False,
    require_crash_probability: bool = False,
    metadata: Mapping[str, Any] | None = None,
) -> MarketDataObservation:
    """Normalize one raw market-data row into scoring inputs.

    ``field_map`` maps canonical field names (for example ``"close"``) to raw
    row keys and takes precedence over built-in aliases.  ETI-5 values can be
    supplied either with canonical names shared with TCWRS or with an ``eti5_``
    prefix, such as ``eti5_close`` and ``eti5_ma20``.
    """

    observed_at_value = _lookup(row, "observed_at", field_map)
    if observed_at_value is None:
        raise ValueError("market data row is missing observed_at/date")
    observed_at = _coerce_date(observed_at_value)

    required = set(_TCWRS_REQUIRED_FIELDS)
    if require_eti5:
        required.update(f"eti5.{name}" for name in _ETI5_REQUIRED_FIELDS)
    if require_crash_probability:
        required.update({"tail_risk", "bcd"})

    missing: list[str] = []
    tcwrs_values: dict[str, Any] = {}
    for name in _TCWRS_FIELD_NAMES:
        value = _lookup(row, name, field_map)
        if value is None:
            if name in _TCWRS_REQUIRED_FIELDS:
                missing.append(name)
            continue
        tcwrs_values[name] = _coerce_field_value(name, value)

    if missing:
        raise ValueError(
            f"market data row missing required TCWRS fields: {', '.join(sorted(missing))}"
        )
    tcwrs_input = TCWRSInput(**tcwrs_values)

    eti5_values: dict[str, Any] = {}
    eti5_missing: list[str] = []
    for name in _ETI5_FIELD_NAMES:
        value = _lookup(row, f"eti5_{name}", field_map)
        if value is None:
            value = _lookup(row, name, field_map)
        if value is None:
            if name in _ETI5_REQUIRED_FIELDS:
                eti5_missing.append(f"eti5.{name}")
            continue
        eti5_values[name] = _coerce_field_value(name, value)

    eti5_input: ETI5Input | None = None
    if eti5_values or require_eti5:
        if eti5_missing:
            if require_eti5:
                raise ValueError(
                    f"market data row missing required ETI-5 fields: {', '.join(sorted(eti5_missing))}"
                )
            eti5_input = None
        else:
            eti5_input = ETI5Input(**eti5_values)

    tail_risk = _optional_float(_lookup(row, "tail_risk", field_map))
    bcd = _optional_float(_lookup(row, "bcd", field_map))
    cp_missing = [
        name
        for name, value in (("tail_risk", tail_risk), ("bcd", bcd))
        if value is None
    ]
    if require_crash_probability and cp_missing:
        raise ValueError(
            f"market data row missing required crash-probability fields: {', '.join(cp_missing)}"
        )

    completeness_missing = sorted(
        set(missing)
        | ({field for field in eti5_missing} if require_eti5 else set())
        | (set(cp_missing) if require_crash_probability else set())
    )
    optional_missing = sorted(
        field
        for field in ("eti5", "tail_risk", "bcd")
        if _optional_component_missing(field, eti5_input, tail_risk, bcd)
    )
    completeness = MarketDataCompleteness(
        required_fields=tuple(sorted(required)),
        missing_fields=tuple(completeness_missing),
        optional_missing_fields=tuple(optional_missing),
    )

    realized_event = _coerce_bool(_lookup(row, "realized_event", field_map) or False)
    return MarketDataObservation(
        observed_at=observed_at,
        tcwrs_input=tcwrs_input,
        eti5_input=eti5_input,
        tail_risk=tail_risk,
        bcd=bcd,
        realized_event=realized_event,
        metadata=dict(metadata or {}),
        completeness=completeness,
        raw=dict(row),
    )


def ingest_market_data_rows(
    rows: Iterable[RawRow],
    *,
    field_map: FieldMap | None = None,
    require_eti5: bool = False,
    require_crash_probability: bool = False,
    metadata: Mapping[str, Any] | None = None,
) -> list[MarketDataObservation]:
    """Normalize and date-sort multiple raw market-data rows."""

    observations = [
        ingest_market_data_row(
            row,
            field_map=field_map,
            require_eti5=require_eti5,
            require_crash_probability=require_crash_probability,
            metadata=metadata,
        )
        for row in rows
    ]
    return sorted(observations, key=lambda observation: observation.observed_at)


def load_market_data_csv(
    path: str | Path,
    *,
    field_map: FieldMap | None = None,
    require_eti5: bool = False,
    require_crash_probability: bool = False,
    metadata: Mapping[str, Any] | None = None,
) -> list[MarketDataObservation]:
    """Load normalized market-data observations from a CSV file."""

    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return ingest_market_data_rows(
            csv.DictReader(handle),
            field_map=field_map,
            require_eti5=require_eti5,
            require_crash_probability=require_crash_probability,
            metadata=metadata,
        )


def derive_price_features(bars: Sequence[MarketPriceBar]) -> dict[str, Any]:
    """Create core price features from chronological daily bars.

    The returned mapping can be merged into a raw ingestion row.  At least 60
    closes are required because TCWRS requires MA60.
    """

    if len(bars) < 60:
        raise ValueError(
            "at least 60 price bars are required to derive TCWRS moving averages"
        )
    closes = [float(bar.close) for bar in bars]
    turnover = [float(bar.turnover_amount) for bar in bars]
    close = closes[-1]
    ma5 = _moving_average(closes, 5)
    ma20 = _moving_average(closes, 20)
    ma60 = _moving_average(closes, 60)
    previous_ma20 = sum(closes[-21:-1]) / 20 if len(closes) >= 21 else ma20
    turnover_ma20 = _moving_average(turnover, 20)
    return {
        "observed_at": _coerce_date(bars[-1].observed_at).isoformat(),
        "close": close,
        "ma5": ma5,
        "ma20": ma20,
        "ma60": ma60,
        "ma20_slope": ma20 - previous_ma20,
        "one_day_return_pct": (
            _pct_change(closes[-2], closes[-1]) if len(closes) >= 2 else 0.0
        ),
        "two_day_return_pct": (
            _pct_change(closes[-3], closes[-1]) if len(closes) >= 3 else 0.0
        ),
        "turnover_amount": turnover[-1],
        "ma20_turnover": turnover_ma20,
    }


def _lookup(row: RawRow, canonical_name: str, field_map: FieldMap | None) -> Any | None:
    if field_map and canonical_name in field_map and field_map[canonical_name] in row:
        return row[field_map[canonical_name]]
    keys = (canonical_name, *_DEFAULT_ALIASES.get(canonical_name, ()))
    for key in keys:
        if key in row and row[key] not in {"", None}:
            return row[key]
    return None


def _coerce_field_value(name: str, value: Any) -> Any:
    if name in _BOOL_FIELD_NAMES:
        return _coerce_bool(value)
    if name in _NUMERIC_FIELD_NAMES:
        if name in _INT_FIELD_NAMES:
            return int(float(value))
        return float(value)
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


def _optional_float(value: Any | None) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)


def _optional_component_missing(
    field_name: str,
    eti5_input: ETI5Input | None,
    tail_risk: float | None,
    bcd: float | None,
) -> bool:
    if field_name == "eti5":
        return eti5_input is None
    if field_name == "tail_risk":
        return tail_risk is None
    if field_name == "bcd":
        return bcd is None
    return False


def _coerce_date(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return date.fromisoformat(text)


def _moving_average(values: Sequence[float], window: int) -> float:
    if len(values) < window:
        raise ValueError(f"at least {window} values are required")
    return sum(values[-window:]) / window


def _pct_change(previous: float, current: float) -> float:
    if previous == 0:
        return 0.0
    return (current - previous) / previous * 100


def _dataclass_as_dict(instance: Any) -> dict[str, Any]:
    return {field.name: getattr(instance, field.name) for field in fields(instance)}
