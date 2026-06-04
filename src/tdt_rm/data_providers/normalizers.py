"""Normalize provider payloads to strict daily input CSV schemas."""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

from .base import REAL_SOURCE_TYPE

STRICT_COLUMNS: dict[str, tuple[str, ...]] = {
    "price": ("trade_date", "provider_source", "source_type", "close", "ma5", "ma20", "ma60", "ma20_slope", "one_day_return_pct", "two_day_return_pct", "close_below_ma20_consecutive_days", "index_5d_return_pct", "return_60d_pct", "previous_ma60", "turnover_amount"),
    "foreign_flow": ("trade_date", "provider_source", "source_type", "foreign_spot_net_buy", "foreign_spot_net_sell", "foreign_spot_net_sell_consecutive_days", "foreign_spot_large_sell", "foreign_large_sell"),
    "fx": ("trade_date", "provider_source", "source_type", "usd_twd_3d_change_pct", "usd_twd_5d_change_pct", "twd_appreciates", "twd_stable", "twd_depreciates_significantly"),
    "breadth": ("trade_date", "provider_source", "source_type", "index_down", "advancing_issues", "declining_issues", "declining_issues_significantly_expand", "declining_issues_significantly_gt_advancing", "declining_gt_advancing_consecutive_days", "breadth_weakens_for_2_days"),
    "futures": ("trade_date", "provider_source", "source_type", "futures_hedging_increases", "futures_hedging_significant", "futures_net_short_increases", "futures_net_short_decreases"),
    "options": ("trade_date", "provider_source", "source_type", "pcr_stable", "pcr_rises", "vix_stable", "vix_rises", "tail_risk", "bcd"),
    "leadership": ("trade_date", "provider_source", "source_type", "count_main_7_below_ma20", "count_main_7_below_ma60", "majority_main_7_assets_above_ma20", "main_7_symbols", "main_7_below_ma20_symbols", "mhs"),
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
            "bcd": _first(row, "bcd", default=min(100.0, max(0.0, 50.0 + max(0.0, pcr - 1.0) * 100.0))),
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
    _ensure_complete(dataset, base)
    return base


def write_strict_csv(path: Path, dataset: str, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = STRICT_COLUMNS[dataset]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerow({column: _serialize(row.get(column, "")) for column in columns})


def _ensure_complete(dataset: str, row: Mapping[str, Any]) -> None:
    missing = [column for column in STRICT_COLUMNS[dataset] if row.get(column) in {None, ""} and column not in {"main_7_below_ma20_symbols"}]
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
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    return value
