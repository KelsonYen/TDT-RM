"""TCWRS module for TDT-RM V5.1.3 Rev.3 Final Freeze.

This module implements only section 3, "TCWRS: Taiwan Crash Warning
Risk Score", of the frozen specification.  The implementation intentionally
keeps every sub-factor score and every intermediate condition used to select
that score so the final score remains auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


ScoreTrace = dict[str, Any]


@dataclass(frozen=True)
class TCWRSInput:
    """Inputs required to score TCWRS exactly from the frozen spec.

    Numeric percentage inputs use percentage points, not decimals.  For example,
    a 3.5% daily decline is represented as ``-3.5``.

    Several specification predicates have no universal raw-data definition in
    the freeze document (for example, "high level", "PCR stable", or
    "declining issues significantly expand").  Those predicates are accepted as
    explicit boolean inputs and are copied into the trace unchanged.
    """

    # Price trend and downside speed (P)
    close: float
    ma5: float
    ma20: float
    ma60: float
    ma20_slope: float
    close_below_ma20_consecutive_days: int = 0
    one_day_return_pct: float = 0.0
    two_day_return_pct: float = 0.0

    # Volume and price-volume efficiency (V)
    turnover_amount: float = 0.0
    ma20_turnover: float = 0.0
    turnover_top_10pct_1y: bool = False
    volume_up: bool = False
    price_up: bool = False
    close_is_red: bool = False
    high_level: bool = False
    long_upper_shadow: bool = False
    close_is_black: bool = False
    long_black_candle: bool = False

    # Foreign investor spot, futures, and options hedging (F)
    foreign_spot_net_buy: float = 0.0
    futures_net_short_decreases: bool = False
    pcr_stable: bool = False
    vix_stable: bool = False
    foreign_spot_small_sell: bool = False
    futures_hedging_significant: bool = False
    foreign_spot_net_sell_consecutive_days: int = 0
    futures_net_short_increases: bool = False
    foreign_spot_large_sell: bool = False
    pcr_rises: bool = False
    vix_rises: bool = False

    # New Taiwan Dollar and cross-border capital flow (X)
    twd_appreciates: bool = False
    twd_stable: bool = False
    usd_twd_3d_change_pct: float = 0.0
    usd_twd_5d_change_pct: float = 0.0
    index_down: bool = False
    twd_depreciates_significantly: bool = False
    foreign_spot_net_sell: bool = False

    # Margin leverage and retail risk (M)
    margin_balance_5d_flat_or_down: bool = False
    hot_stock_margin_fast_increase: bool = False
    margin_balance_5d_increases: bool = False
    index_5d_return_pct: float = 0.0
    margin_balance_5d_decline_pct: float = 0.0
    margin_not_retreating: bool = False

    # Market breadth deterioration (B)
    index_up_or_flat: bool = False
    advancing_issues: int = 0
    declining_issues: int = 0
    declining_issues_significantly_expand: bool = False
    declining_issues_significantly_gt_advancing: bool = False
    declining_gt_advancing_consecutive_days: int = 0

    # Large-cap and mainstream stock health (L)
    majority_main_7_assets_above_ma20: bool = False
    count_main_7_below_ma20: int = 0
    count_main_7_below_ma60: int = 0

    # Global risk and external pressure (G)
    us_stocks_stable: bool = False
    sox_stable: bool = False
    vix_stable_global: bool = False
    sox: float = 0.0
    sox_ma20: float = 0.0
    sox_ma60: float = 0.0
    nasdaq: float = 0.0
    nasdaq_ma20: float = 0.0
    vix_rises_fast: bool = False
    us_tech_leadership_weakens: bool = False
    vix_spikes: bool = False


@dataclass(frozen=True)
class TCWRSFactorResult:
    """Auditable result for one TCWRS sub-factor."""

    code: str
    name: str
    max_score: int
    score: int
    matched_rule: str
    conditions: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TCWRSResult:
    """Auditable TCWRS result with all intermediate factor traces."""

    total: int
    factors: Mapping[str, TCWRSFactorResult]

    def as_dict(self) -> dict[str, Any]:
        """Return a serializable dict preserving all score traces."""

        return {
            "total": self.total,
            "factors": {
                code: {
                    "code": factor.code,
                    "name": factor.name,
                    "max_score": factor.max_score,
                    "score": factor.score,
                    "matched_rule": factor.matched_rule,
                    "conditions": dict(factor.conditions),
                }
                for code, factor in self.factors.items()
            },
        }


def _factor(
    code: str,
    name: str,
    max_score: int,
    score: int,
    matched_rule: str,
    conditions: ScoreTrace,
) -> TCWRSFactorResult:
    if score < 0 or score > max_score:
        raise ValueError(f"{code} score {score} outside 0-{max_score}")
    return TCWRSFactorResult(code, name, max_score, score, matched_rule, conditions)


def score_p(data: TCWRSInput) -> TCWRSFactorResult:
    """Score P: Price Trend and Downside Speed."""

    conditions: ScoreTrace = {
        "close_gt_ma20_and_ma20_slope_gt_0": data.close > data.ma20 and data.ma20_slope > 0,
        "close_lt_ma5_and_close_gte_ma20": data.close < data.ma5 and data.close >= data.ma20,
        "close_below_ma20_for_1_day": data.close < data.ma20 and data.close_below_ma20_consecutive_days == 1,
        "close_below_ma20_for_2_consecutive_days": data.close < data.ma20
        and data.close_below_ma20_consecutive_days >= 2,
        "close_lt_ma60": data.close < data.ma60,
        "one_day_return_lte_minus_3_5_or_two_day_return_lte_minus_5_5": data.one_day_return_pct <= -3.5
        or data.two_day_return_pct <= -5.5,
        "raw": {
            "close": data.close,
            "ma5": data.ma5,
            "ma20": data.ma20,
            "ma60": data.ma60,
            "ma20_slope": data.ma20_slope,
            "close_below_ma20_consecutive_days": data.close_below_ma20_consecutive_days,
            "one_day_return_pct": data.one_day_return_pct,
            "two_day_return_pct": data.two_day_return_pct,
        },
    }
    if conditions["close_gt_ma20_and_ma20_slope_gt_0"]:
        score, rule = 0, "close > MA20 AND MA20_slope > 0"
    elif conditions["close_lt_ma5_and_close_gte_ma20"]:
        score, rule = 4, "close < MA5 AND close >= MA20"
    elif conditions["close_below_ma20_for_1_day"]:
        score, rule = 8, "close < MA20 for 1 day"
    elif conditions["close_below_ma20_for_2_consecutive_days"]:
        score, rule = 12, "close < MA20 for 2 consecutive days"
    elif conditions["close_lt_ma60"]:
        score, rule = 15, "close < MA60"
    elif conditions["one_day_return_lte_minus_3_5_or_two_day_return_lte_minus_5_5"]:
        score, rule = 18, "one_day_return <= -3.5% OR two_day_return <= -5.5%"
    else:
        score, rule = 0, "no TCWRS_P risk condition matched"
    return _factor("P", "價格趨勢與跌速", 18, score, rule, conditions)


def score_v(data: TCWRSInput) -> TCWRSFactorResult:
    """Score V: Volume and Price-Volume Efficiency."""

    high_volume = (
        data.turnover_amount > data.ma20_turnover * 1.5 if data.ma20_turnover else False
    ) or data.turnover_top_10pct_1y
    conditions: ScoreTrace = {
        "high_volume": high_volume,
        "volume_up_and_price_up_and_close_is_red": data.volume_up and data.price_up and data.close_is_red,
        "high_level_and_high_volume_and_close_is_red": data.high_level and high_volume and data.close_is_red,
        "high_level_and_long_upper_shadow": data.high_level and data.long_upper_shadow,
        "high_volume_and_close_is_black": high_volume and data.close_is_black,
        "high_volume_and_long_black_candle_and_close_lt_ma20": high_volume
        and data.long_black_candle
        and data.close < data.ma20,
        "raw": {
            "turnover_amount": data.turnover_amount,
            "ma20_turnover": data.ma20_turnover,
            "turnover_top_10pct_1y": data.turnover_top_10pct_1y,
            "volume_up": data.volume_up,
            "price_up": data.price_up,
            "close_is_red": data.close_is_red,
            "high_level": data.high_level,
            "long_upper_shadow": data.long_upper_shadow,
            "close_is_black": data.close_is_black,
            "long_black_candle": data.long_black_candle,
            "close": data.close,
            "ma20": data.ma20,
        },
    }
    if conditions["volume_up_and_price_up_and_close_is_red"]:
        score, rule = 0, "volume_up AND price_up AND close_is_red"
    elif conditions["high_level_and_high_volume_and_close_is_red"]:
        score, rule = 3, "high_level AND high_volume AND close_is_red"
    elif conditions["high_level_and_long_upper_shadow"]:
        score, rule = 6, "high_level AND long_upper_shadow"
    elif conditions["high_volume_and_close_is_black"]:
        score, rule = 9, "high_volume AND close_is_black"
    elif conditions["high_volume_and_long_black_candle_and_close_lt_ma20"]:
        score, rule = 12, "high_volume AND long_black_candle AND close < MA20"
    else:
        score, rule = 0, "no TCWRS_V risk condition matched"
    return _factor("V", "成交量與價量效率", 12, score, rule, conditions)


def score_f(data: TCWRSInput) -> TCWRSFactorResult:
    """Score F: Foreign Investor Spot, Futures, and Options Hedging."""

    conditions: ScoreTrace = {
        "foreign_spot_net_buy_gt_0_and_futures_net_short_decreases_and_pcr_stable_and_vix_stable": data.foreign_spot_net_buy > 0
        and data.futures_net_short_decreases
        and data.pcr_stable
        and data.vix_stable,
        "foreign_spot_small_sell_and_not_futures_hedging_significant": data.foreign_spot_small_sell
        and not data.futures_hedging_significant,
        "foreign_spot_net_sell_for_2_consecutive_days": data.foreign_spot_net_sell_consecutive_days >= 2,
        "foreign_spot_net_sell_for_3_consecutive_days_and_futures_net_short_increases": data.foreign_spot_net_sell_consecutive_days >= 3
        and data.futures_net_short_increases,
        "foreign_spot_large_sell_and_futures_net_short_increases_and_pcr_or_vix_rises": data.foreign_spot_large_sell
        and data.futures_net_short_increases
        and (data.pcr_rises or data.vix_rises),
        "raw": {
            "foreign_spot_net_buy": data.foreign_spot_net_buy,
            "foreign_spot_net_sell_consecutive_days": data.foreign_spot_net_sell_consecutive_days,
            "futures_net_short_increases": data.futures_net_short_increases,
            "foreign_spot_large_sell": data.foreign_spot_large_sell,
            "pcr_rises": data.pcr_rises,
            "vix_rises": data.vix_rises,
        },
    }
    if conditions["foreign_spot_net_buy_gt_0_and_futures_net_short_decreases_and_pcr_stable_and_vix_stable"]:
        score, rule = 0, "foreign_spot_net_buy > 0 AND futures_net_short_decreases AND PCR_stable AND VIX_stable"
    elif conditions["foreign_spot_small_sell_and_not_futures_hedging_significant"]:
        score, rule = 4, "foreign_spot_small_sell AND NOT futures_hedging_significant"
    elif conditions["foreign_spot_net_sell_for_2_consecutive_days"]:
        score, rule = 8, "foreign_spot_net_sell for 2 consecutive days"
    elif conditions["foreign_spot_net_sell_for_3_consecutive_days_and_futures_net_short_increases"]:
        score, rule = 11, "foreign_spot_net_sell for 3 consecutive days AND futures_net_short_increases"
    elif conditions["foreign_spot_large_sell_and_futures_net_short_increases_and_pcr_or_vix_rises"]:
        score, rule = 15, "foreign_spot_large_sell AND futures_net_short_increases AND (PCR_rises OR VIX_rises)"
    else:
        score, rule = 0, "no TCWRS_F risk condition matched"
    return _factor("F", "外資現貨、期貨、選擇權避險", 15, score, rule, conditions)


def score_x(data: TCWRSInput) -> TCWRSFactorResult:
    """Score X: New Taiwan Dollar and Cross-Border Capital Flow."""

    conditions: ScoreTrace = {
        "twd_appreciates_or_twd_stable": data.twd_appreciates or data.twd_stable,
        "usd_twd_3d_change_gt_0_5": data.usd_twd_3d_change_pct > 0.5,
        "usd_twd_5d_change_gt_1_0": data.usd_twd_5d_change_pct > 1.0,
        "index_down_and_twd_depreciates_significantly_and_foreign_spot_net_sell": data.index_down
        and data.twd_depreciates_significantly
        and data.foreign_spot_net_sell,
        "raw": {
            "usd_twd_3d_change_pct": data.usd_twd_3d_change_pct,
            "usd_twd_5d_change_pct": data.usd_twd_5d_change_pct,
            "index_down": data.index_down,
            "foreign_spot_net_sell": data.foreign_spot_net_sell,
        },
    }
    if conditions["twd_appreciates_or_twd_stable"]:
        score, rule = 0, "TWD_appreciates OR TWD_stable"
    elif conditions["usd_twd_3d_change_gt_0_5"]:
        score, rule = 4, "USD_TWD_3d_change > 0.5%"
    elif conditions["usd_twd_5d_change_gt_1_0"]:
        score, rule = 8, "USD_TWD_5d_change > 1.0%"
    elif conditions["index_down_and_twd_depreciates_significantly_and_foreign_spot_net_sell"]:
        score, rule = 12, "index_down AND TWD_depreciates_significantly AND foreign_spot_net_sell"
    else:
        score, rule = 0, "no TCWRS_X risk condition matched"
    return _factor("X", "新台幣與跨境資金", 12, score, rule, conditions)


def score_m(data: TCWRSInput) -> TCWRSFactorResult:
    """Score M: Margin Leverage and Retail Risk."""

    conditions: ScoreTrace = {
        "margin_balance_5d_flat_or_down_and_not_hot_stock_margin_fast_increase": data.margin_balance_5d_flat_or_down
        and not data.hot_stock_margin_fast_increase,
        "margin_balance_5d_increases_and_close_gte_ma20": data.margin_balance_5d_increases
        and data.close >= data.ma20,
        "index_5d_return_lt_minus_3_and_margin_balance_5d_decline_lt_0_5": data.index_5d_return_pct < -3.0
        and data.margin_balance_5d_decline_pct < 0.5,
        "index_down_and_margin_not_retreating_and_hot_stock_margin_fast_increase": data.index_down
        and data.margin_not_retreating
        and data.hot_stock_margin_fast_increase,
        "raw": {
            "index_5d_return_pct": data.index_5d_return_pct,
            "margin_balance_5d_decline_pct": data.margin_balance_5d_decline_pct,
            "close": data.close,
            "ma20": data.ma20,
        },
    }
    if conditions["margin_balance_5d_flat_or_down_and_not_hot_stock_margin_fast_increase"]:
        score, rule = 0, "margin_balance_5d_flat_or_down AND NOT hot_stock_margin_fast_increase"
    elif conditions["margin_balance_5d_increases_and_close_gte_ma20"]:
        score, rule = 4, "margin_balance_5d_increases AND close >= MA20"
    elif conditions["index_5d_return_lt_minus_3_and_margin_balance_5d_decline_lt_0_5"]:
        score, rule = 8, "index_5d_return < -3% AND margin_balance_5d_decline < 0.5%"
    elif conditions["index_down_and_margin_not_retreating_and_hot_stock_margin_fast_increase"]:
        score, rule = 12, "index_down AND margin_not_retreating AND hot_stock_margin_fast_increase"
    else:
        score, rule = 0, "no TCWRS_M risk condition matched"
    return _factor("M", "融資槓桿與散戶風險", 12, score, rule, conditions)


def score_b(data: TCWRSInput) -> TCWRSFactorResult:
    """Score B: Market Breadth Deterioration."""

    conditions: ScoreTrace = {
        "index_up_or_flat_and_advancing_gt_declining": data.index_up_or_flat
        and data.advancing_issues > data.declining_issues,
        "index_down_and_not_declining_issues_significantly_expand": data.index_down
        and not data.declining_issues_significantly_expand,
        "index_down_and_declining_issues_significantly_gt_advancing": data.index_down
        and data.declining_issues_significantly_gt_advancing,
        "close_lt_ma20_and_declining_gt_advancing_for_2_consecutive_days": data.close < data.ma20
        and data.declining_gt_advancing_consecutive_days >= 2,
        "raw": {
            "index_up_or_flat": data.index_up_or_flat,
            "index_down": data.index_down,
            "advancing_issues": data.advancing_issues,
            "declining_issues": data.declining_issues,
            "declining_gt_advancing_consecutive_days": data.declining_gt_advancing_consecutive_days,
            "close": data.close,
            "ma20": data.ma20,
        },
    }
    if conditions["index_up_or_flat_and_advancing_gt_declining"]:
        score, rule = 0, "index_up_or_flat AND advancing_issues > declining_issues"
    elif conditions["index_down_and_not_declining_issues_significantly_expand"]:
        score, rule = 4, "index_down AND NOT declining_issues_significantly_expand"
    elif conditions["index_down_and_declining_issues_significantly_gt_advancing"]:
        score, rule = 8, "index_down AND declining_issues >> advancing_issues"
    elif conditions["close_lt_ma20_and_declining_gt_advancing_for_2_consecutive_days"]:
        score, rule = 12, "close < MA20 AND declining_issues >> advancing_issues for 2 consecutive days"
    else:
        score, rule = 0, "no TCWRS_B risk condition matched"
    return _factor("B", "市場廣度惡化", 12, score, rule, conditions)


def score_l(data: TCWRSInput) -> TCWRSFactorResult:
    """Score L: Large-Cap and Mainstream Stock Health."""

    conditions: ScoreTrace = {
        "majority_main_7_assets_above_ma20": data.majority_main_7_assets_above_ma20,
        "count_main_7_below_ma20_eq_2": data.count_main_7_below_ma20 == 2,
        "count_main_7_below_ma20_eq_4": data.count_main_7_below_ma20 == 4,
        "count_main_7_below_ma20_eq_5": data.count_main_7_below_ma20 == 5,
        "count_main_7_below_ma60_gt_3": data.count_main_7_below_ma60 > 3,
        "raw": {
            "count_main_7_below_ma20": data.count_main_7_below_ma20,
            "count_main_7_below_ma60": data.count_main_7_below_ma60,
        },
    }
    if conditions["majority_main_7_assets_above_ma20"]:
        score, rule = 0, "majority_main_7_assets_above_MA20"
    elif conditions["count_main_7_below_ma20_eq_2"]:
        score, rule = 3, "count_main_7_below_MA20 == 2"
    elif conditions["count_main_7_below_ma20_eq_4"]:
        score, rule = 6, "count_main_7_below_MA20 == 4"
    elif conditions["count_main_7_below_ma20_eq_5"]:
        score, rule = 8, "count_main_7_below_MA20 == 5"
    elif conditions["count_main_7_below_ma60_gt_3"]:
        score, rule = 10, "count_main_7_below_MA60 > 3"
    else:
        score, rule = 0, "no TCWRS_L risk condition matched"
    return _factor("L", "權值股與主流股健康度", 10, score, rule, conditions)


def score_g(data: TCWRSInput) -> TCWRSFactorResult:
    """Score G: Global Risk and External Pressure."""

    conditions: ScoreTrace = {
        "us_stocks_stable_and_sox_stable_and_vix_stable": data.us_stocks_stable
        and data.sox_stable
        and data.vix_stable_global,
        "sox_lt_sox_ma20_or_nasdaq_lt_nasdaq_ma20": data.sox < data.sox_ma20
        or data.nasdaq < data.nasdaq_ma20,
        "sox_lt_sox_ma60_or_vix_rises_fast": data.sox < data.sox_ma60 or data.vix_rises_fast,
        "us_tech_leadership_weakens_and_vix_spikes_and_taiex_lt_ma20_or_ma60": data.us_tech_leadership_weakens
        and data.vix_spikes
        and (data.close < data.ma20 or data.close < data.ma60),
        "raw": {
            "sox": data.sox,
            "sox_ma20": data.sox_ma20,
            "sox_ma60": data.sox_ma60,
            "nasdaq": data.nasdaq,
            "nasdaq_ma20": data.nasdaq_ma20,
            "close": data.close,
            "ma20": data.ma20,
            "ma60": data.ma60,
        },
    }
    if conditions["us_stocks_stable_and_sox_stable_and_vix_stable"]:
        score, rule = 0, "US_stocks_stable AND SOX_stable AND VIX_stable"
    elif conditions["sox_lt_sox_ma20_or_nasdaq_lt_nasdaq_ma20"]:
        score, rule = 3, "SOX < SOX_MA20 OR Nasdaq < Nasdaq_MA20"
    elif conditions["sox_lt_sox_ma60_or_vix_rises_fast"]:
        score, rule = 6, "SOX < SOX_MA60 OR VIX_rises_fast"
    elif conditions["us_tech_leadership_weakens_and_vix_spikes_and_taiex_lt_ma20_or_ma60"]:
        score, rule = 9, "US_tech_leadership_weakens AND VIX_spikes AND (TAIEX < MA20 OR TAIEX < MA60)"
    else:
        score, rule = 0, "no TCWRS_G risk condition matched"
    return _factor("G", "全球風險與外部壓力", 9, score, rule, conditions)


def score_tcwrs(data: TCWRSInput) -> TCWRSResult:
    """Score the complete TCWRS module and retain every intermediate trace."""

    factors = {
        factor.code: factor
        for factor in (
            score_p(data),
            score_v(data),
            score_f(data),
            score_x(data),
            score_m(data),
            score_b(data),
            score_l(data),
            score_g(data),
        )
    }
    total = sum(factor.score for factor in factors.values())
    if total < 0 or total > 100:
        raise ValueError(f"TCWRS total {total} outside 0-100")
    return TCWRSResult(total=total, factors=factors)
