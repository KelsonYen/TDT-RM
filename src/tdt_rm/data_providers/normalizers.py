"""Normalize provider payloads to strict daily input CSV schemas."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

from .base import REAL_SOURCE_TYPE, ReconciliationCheck

BCD_RECOVERY_EXTRA_COLUMNS = (
    "breadth_history",
    "main7_closes",
    "main7_previous_closes",
    "main7_turnover_amounts",
    "main7_returns",
    "main7_weights",
    "main7_concentration",
    "sector_returns",
    "sector_above_ma20",
    "sector_breadth",
    "sector_diffusion",
    "otc_return_pct",
    "small_mid_breadth",
    "small_mid_weakness",
    "turnover_concentration_topn",
    "turnover_concentration",
)
STRICT_COLUMNS: dict[str, tuple[str, ...]] = {
    "price": ("trade_date", "provider_source", "source_type", "close", "ma5", "ma20", "ma60", "ma20_slope", "one_day_return_pct", "two_day_return_pct", "close_below_ma20_consecutive_days", "index_5d_return_pct", "return_60d_pct", "previous_ma60", "turnover_amount"),
    "foreign_flow": ("trade_date", "provider_source", "source_type", "foreign_spot_net_buy", "foreign_spot_net_sell", "foreign_spot_net_sell_consecutive_days", "foreign_spot_large_sell", "foreign_large_sell"),
    "fx": ("trade_date", "provider_source", "source_type", "usd_twd_3d_change_pct", "usd_twd_5d_change_pct", "twd_appreciates", "twd_stable", "twd_depreciates_significantly"),
    "breadth": ("trade_date", "provider_source", "source_type", "index_down", "advancing_issues", "declining_issues", "declining_issues_significantly_expand", "declining_issues_significantly_gt_advancing", "declining_gt_advancing_consecutive_days", "breadth_weakens_for_2_days", *BCD_RECOVERY_EXTRA_COLUMNS),
    "futures": ("trade_date", "provider_source", "source_type", "futures_hedging_increases", "futures_hedging_significant", "futures_net_short_increases", "futures_net_short_decreases"),
    "options": ("trade_date", "provider_source", "source_type", "pcr_stable", "pcr_rises", "vix_stable", "vix_rises", "tail_risk"),
    "leadership": ("trade_date", "provider_source", "source_type", "count_main_7_below_ma20", "count_main_7_below_ma60", "majority_main_7_assets_above_ma20", "main_7_symbols", "main_7_below_ma20_symbols", "mhs", *BCD_RECOVERY_EXTRA_COLUMNS),
    "margin": ("trade_date", "provider_source", "source_type", "margin_balance_5d_flat_or_down", "hot_stock_margin_fast_increase", "margin_balance_5d_increases", "index_5d_return_pct", "margin_balance_5d_decline_pct", "margin_not_retreating", *BCD_RECOVERY_EXTRA_COLUMNS),
}
OPTIONAL_STRICT_COLUMNS = set(BCD_RECOVERY_EXTRA_COLUMNS) | {"main_7_below_ma20_symbols"}

_NUMERIC_COLUMNS: dict[str, tuple[str, ...]] = {
    "price": ("close", "ma5", "ma20", "ma60", "ma20_slope", "one_day_return_pct", "two_day_return_pct", "close_below_ma20_consecutive_days", "index_5d_return_pct", "return_60d_pct", "previous_ma60", "turnover_amount"),
    "foreign_flow": ("foreign_spot_net_buy", "foreign_spot_net_sell", "foreign_spot_net_sell_consecutive_days"),
    "fx": ("usd_twd_3d_change_pct", "usd_twd_5d_change_pct"),
    "breadth": ("advancing_issues", "declining_issues", "declining_gt_advancing_consecutive_days"),
    "options": ("tail_risk",),
    "leadership": ("count_main_7_below_ma20", "count_main_7_below_ma60", "mhs"),
    "margin": ("index_5d_return_pct", "margin_balance_5d_decline_pct"),
}
_BOOL_COLUMNS: dict[str, tuple[str, ...]] = {
    "foreign_flow": ("foreign_spot_large_sell", "foreign_large_sell"),
    "fx": ("twd_appreciates", "twd_stable", "twd_depreciates_significantly"),
    "breadth": ("index_down", "declining_issues_significantly_expand", "declining_issues_significantly_gt_advancing", "breadth_weakens_for_2_days"),
    "futures": ("futures_hedging_increases", "futures_hedging_significant", "futures_net_short_increases", "futures_net_short_decreases"),
    "options": ("pcr_stable", "pcr_rises", "vix_stable", "vix_rises"),
    "leadership": ("majority_main_7_assets_above_ma20",),
    "margin": ("margin_balance_5d_flat_or_down", "hot_stock_margin_fast_increase", "margin_balance_5d_increases", "margin_not_retreating"),
}


def normalize_public_row(dataset: str, row: Mapping[str, Any], *, trade_date: date, provider_source: str) -> dict[str, Any]:
    base: dict[str, Any] = {"trade_date": trade_date.isoformat(), "provider_source": provider_source, "source_type": REAL_SOURCE_TYPE}
    if dataset == "price":
        out = {
            "close": _first(row, "close", "taiex_close", "index_close"),
            "ma5": _first(row, "ma5", "taiex_ma5", "index_ma5"),
            "ma20": _first(row, "ma20", "taiex_ma20", "index_ma20"),
            "ma60": _first(row, "ma60", "taiex_ma60", "index_ma60"),
            "ma20_slope": _first(row, "ma20_slope", "taiex_ma20_slope", "index_ma20_slope", default=0),
            "one_day_return_pct": _first(row, "one_day_return_pct", default=0),
            "two_day_return_pct": _first(row, "two_day_return_pct", default=0),
            "close_below_ma20_consecutive_days": _first(row, "close_below_ma20_consecutive_days", default=0),
            "index_5d_return_pct": _first(row, "index_5d_return_pct", default=0),
            "return_60d_pct": _first(row, "return_60d_pct", default=0),
            "previous_ma60": _first(row, "previous_ma60", "ma60"),
            "turnover_amount": _first(row, "turnover_amount", "taiex_turnover", "turnover", default=0),
        }
    elif dataset == "foreign_flow":
        net_buy = _float(_first(row, "foreign_spot_net_buy", default=0))
        net_sell = _first(row, "foreign_spot_net_sell")
        if net_sell is None:
            net_sell = abs(min(net_buy, 0.0))
        out = {
            "foreign_spot_net_buy": net_buy,
            "foreign_spot_net_sell": net_sell,
            "foreign_spot_net_sell_consecutive_days": _first(row, "foreign_spot_net_sell_consecutive_days", default=0),
            "foreign_spot_large_sell": _first(row, "foreign_spot_large_sell", default=_float(net_sell) >= 15_000_000_000),
            "foreign_large_sell": _first(row, "foreign_large_sell", default=_float(net_sell) >= 15_000_000_000),
        }
    elif dataset == "fx":
        chg3 = _first(row, "usd_twd_3d_change_pct", default=0)
        chg5 = _first(row, "usd_twd_5d_change_pct", default=0)
        out = {
            "usd_twd_3d_change_pct": chg3,
            "usd_twd_5d_change_pct": chg5,
            "twd_appreciates": _first(row, "twd_appreciates", default=_float(chg5) < -0.5),
            "twd_stable": _first(row, "twd_stable", default=abs(_float(chg5)) <= 0.5),
            "twd_depreciates_significantly": _first(row, "twd_depreciates_significantly", default=_float(chg5) >= 1.0),
        }
    elif dataset == "breadth":
        adv = _float(_first(row, "advancing_issues", "advancers", default=0))
        dec = _float(_first(row, "declining_issues", "decliners", default=0))
        out = {
            "index_down": _first(row, "index_down", default=False),
            "advancing_issues": adv,
            "declining_issues": dec,
            "declining_issues_significantly_expand": _first(row, "declining_issues_significantly_expand", default=dec >= max(adv * 1.5, 700)),
            "declining_issues_significantly_gt_advancing": _first(row, "declining_issues_significantly_gt_advancing", default=dec > adv * 1.5),
            "declining_gt_advancing_consecutive_days": _first(row, "declining_gt_advancing_consecutive_days", default=1 if dec > adv else 0),
            "breadth_weakens_for_2_days": _first(row, "breadth_weakens_for_2_days", default=False),
        }
    elif dataset == "futures":
        oi = _first(row, "txf_open_interest", "open_interest")
        out = {
            "futures_hedging_increases": _first(row, "futures_hedging_increases", default=False),
            "futures_hedging_significant": _first(row, "futures_hedging_significant", default=False),
            "futures_net_short_increases": _first(row, "futures_net_short_increases", default=False if oi is None else bool(_float(oi) > 0)),
            "futures_net_short_decreases": _first(row, "futures_net_short_decreases", default=False),
        }
    elif dataset == "options":
        pcr = _float(_first(row, "txo_put_call_ratio", "pcr", default=1.0))
        vix = _float(_first(row, "taifex_vix", "vix", default=0.0))
        out = {
            "pcr_stable": _first(row, "pcr_stable", default=0.9 <= pcr <= 1.1),
            "pcr_rises": _first(row, "pcr_rises", default=pcr > 1.1),
            "vix_stable": _first(row, "vix_stable", default=vix < 25 if vix else True),
            "vix_rises": _first(row, "vix_rises", default=vix >= 25 if vix else False),
            "tail_risk": _first(row, "tail_risk", default=min(100.0, max(0.0, 50.0 + (pcr - 1.0) * 100.0 + max(0.0, vix - 20.0)))),
        }
    elif dataset == "margin":
        decline = _first(row, "margin_balance_5d_decline_pct", default=0)
        increases = _first(row, "margin_balance_5d_increases", default=False)
        out = {
            "margin_balance_5d_flat_or_down": _first(row, "margin_balance_5d_flat_or_down", default=not bool(increases)),
            "hot_stock_margin_fast_increase": _first(row, "hot_stock_margin_fast_increase", default=False),
            "margin_balance_5d_increases": increases,
            "index_5d_return_pct": _first(row, "index_5d_return_pct", default=0),
            "margin_balance_5d_decline_pct": decline,
            "margin_not_retreating": _first(row, "margin_not_retreating", default=_float(decline) <= 0),
        }
    elif dataset == "leadership":
        below20 = int(_float(_first(row, "count_main_7_below_ma20", default=0)))
        symbols = str(_first(row, "main_7_symbols", default=""))
        total = len([item for item in symbols.replace(";", ",").split(",") if item]) or 7
        out = {
            "count_main_7_below_ma20": below20,
            "count_main_7_below_ma60": _first(row, "count_main_7_below_ma60", default=0),
            "majority_main_7_assets_above_ma20": _first(row, "majority_main_7_assets_above_ma20", default=below20 < (total / 2)),
            "main_7_symbols": symbols,
            "main_7_below_ma20_symbols": _first(row, "main_7_below_ma20_symbols", default=""),
            "mhs": _first(row, "mhs", default=round(100.0 * (total - below20) / total, 4)),
        }
    else:
        raise ValueError(f"unsupported dataset: {dataset}")
    base.update(out)
    for column in BCD_RECOVERY_EXTRA_COLUMNS:
        if column in row:
            base[column] = row[column]
    _ensure_complete(dataset, base)
    return base


def write_strict_csv(path: Path, dataset: str, row: Mapping[str, Any]) -> None:
    errors = validate_strict_row(dataset, row)
    if errors:
        raise ValueError(f"{dataset} strict schema validation failed: " + "; ".join(errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = STRICT_COLUMNS[dataset]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="raise")
        writer.writeheader()
        writer.writerow({column: _serialize(row.get(column, "")) for column in columns})


def validate_strict_row(dataset: str, row: Mapping[str, Any]) -> list[str]:
    if dataset not in STRICT_COLUMNS:
        return [f"unsupported dataset: {dataset}"]
    errors: list[str] = []
    for column in STRICT_COLUMNS[dataset]:
        value = row.get(column)
        if (value is None or value == "") and column not in OPTIONAL_STRICT_COLUMNS:
            errors.append(f"missing required field {column}")
    if row.get("source_type") != REAL_SOURCE_TYPE:
        errors.append(f"source_type must be {REAL_SOURCE_TYPE!r}")
    if str(row.get("trade_date") or "") == "":
        errors.append("trade_date is required")
    for column in _NUMERIC_COLUMNS.get(dataset, ()):  # parseability/range, not scoring.
        value = row.get(column)
        if value is None or value == "":
            continue
        try:
            number = _float(value)
        except (TypeError, ValueError):
            errors.append(f"numeric field {column} is not parseable: {value!r}")
            continue
        if column in {"close", "ma5", "ma20", "ma60", "previous_ma60"} and number <= 0:
            errors.append(f"numeric field {column} must be positive")
        if column in {"tail_risk", "mhs"} and not 0 <= number <= 100:
            errors.append(f"numeric field {column} must be in [0, 100]")
    for column in _BOOL_COLUMNS.get(dataset, ()):  # strict bool normalization.
        if row.get(column) in {None, ""}:
            continue
        if str(row.get(column)).strip().lower() not in {"true", "false", "1", "0", "yes", "no", "y", "n"}:
            errors.append(f"boolean field {column} is not parseable: {row.get(column)!r}")
    return errors


def reconciliation_checks(dataset: str, row: Mapping[str, Any]) -> tuple[ReconciliationCheck, ...]:
    checks: list[ReconciliationCheck] = []
    schema_errors = validate_strict_row(dataset, row)
    checks.append(ReconciliationCheck("strict_schema", "failed" if schema_errors else "passed", "; ".join(schema_errors)))
    if dataset == "price":
        close = _float(row.get("close"))
        ma20 = _float(row.get("ma20"))
        ma60 = _float(row.get("ma60"))
        positive = close > 0 and ma20 > 0 and ma60 > 0
        checks.append(ReconciliationCheck("price_positive", "passed" if positive else "failed", "close/MA values must be positive"))
        ratio_ok = positive and 0.5 <= close / ma20 <= 1.5 and 0.5 <= close / ma60 <= 1.5
        checks.append(ReconciliationCheck("ma_ratio_sanity", "passed" if ratio_ok else "failed", "TAIEX close diverges too far from moving averages"))
    elif dataset == "foreign_flow":
        net_buy = _float(row.get("foreign_spot_net_buy"))
        net_sell = _float(row.get("foreign_spot_net_sell"))
        checks.append(ReconciliationCheck("foreign_buy_sell_sign", "passed" if net_sell >= 0 and (net_buy >= 0 or net_sell > 0) else "failed", "net sell must reconcile with net buy sign"))
    elif dataset == "leadership":
        symbols = [item for item in str(row.get("main_7_symbols") or "").replace(";", ",").split(",") if item]
        below20 = int(_float(row.get("count_main_7_below_ma20")))
        below60 = int(_float(row.get("count_main_7_below_ma60")))
        total = len(symbols) or 7
        checks.append(ReconciliationCheck("leadership_counts", "passed" if 0 <= below20 <= total and 0 <= below60 <= total else "failed", "Main-7 below-MA counts exceed configured symbol count"))
    elif dataset == "fx":
        chg3 = abs(_float(row.get("usd_twd_3d_change_pct")))
        chg5 = abs(_float(row.get("usd_twd_5d_change_pct")))
        checks.append(ReconciliationCheck("fx_change_sanity", "passed" if chg3 <= 20 and chg5 <= 25 else "failed", "USD/TWD percentage change outside sanity bounds"))
    elif dataset == "options":
        checks.append(ReconciliationCheck("scores_range", "passed" if 0 <= _float(row.get("tail_risk")) <= 100 else "failed", "tail_risk must be in [0, 100]; provider BCD is forbidden"))
    else:
        checks.append(ReconciliationCheck("dataset_invariants", "passed", "no extra invariants configured"))
    return tuple(checks)


def _ensure_complete(dataset: str, row: Mapping[str, Any]) -> None:
    missing = [column for column in STRICT_COLUMNS[dataset] if (row.get(column) is None or row.get(column) == "") and column not in OPTIONAL_STRICT_COLUMNS]
    if missing:
        raise ValueError(f"{dataset} normalized row missing required fields: {', '.join(missing)}")


def _first(row: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in row and row[key] not in {None, ""}:
            return row[key]
    return default


def _float(value: Any) -> float:
    if value in {None, ""}:
        return 0.0
    return float(str(value).replace(",", ""))


def _serialize(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return value
