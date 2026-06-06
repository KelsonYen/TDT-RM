"""Breadth Concentration Divergence (BCD) scoring.

BCD is an auditable concentration / narrow-rally detector.  It deliberately
keeps missing inputs out of component scores instead of substituting neutral
values, and returns a full trace for production review and backtests.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class BreadthBar:
    """One breadth observation for current or historical participation checks."""

    advancing_issues: int
    declining_issues: int
    taiex_return_pct: float | None = None
    trade_date: str | None = None

    @property
    def total_issues(self) -> int:
        return self.advancing_issues + self.declining_issues

    @property
    def advance_ratio(self) -> float | None:
        total = self.total_issues
        return None if total <= 0 else self.advancing_issues / total


@dataclass(frozen=True)
class BCDInput:
    """Required and optional BCD inputs with explicit absence semantics."""

    taiex_return_pct: float
    advancing_issues: int
    declining_issues: int
    breadth_history: tuple[BreadthBar, ...]
    main7_returns: Mapping[str, float]
    main7_weights: Mapping[str, float]
    sector_returns: Mapping[str, float]
    sector_above_ma20: Mapping[str, bool]
    otc_return_pct: float | None
    small_mid_breadth: BreadthBar | None
    turnover_concentration_topn: float | None


@dataclass(frozen=True)
class BCDResult:
    """Fully explainable BCD output."""

    final_score: float
    component_scores: Mapping[str, float]
    raw_inputs: Mapping[str, Any]
    threshold_hits: Mapping[str, bool]
    missing_components: tuple[str, ...]
    source_fields: Mapping[str, str]
    data_quality_status: str = "complete"

    def as_dict(self) -> dict[str, Any]:
        return {
            "final_score": self.final_score,
            "component_scores": dict(self.component_scores),
            "raw_inputs": dict(self.raw_inputs),
            "threshold_hits": dict(self.threshold_hits),
            "missing_components": list(self.missing_components),
            "source_fields": dict(self.source_fields),
            "data_quality_status": self.data_quality_status,
        }


_COMPONENTS = (
    "index_breadth_divergence",
    "main7_concentration",
    "sector_diffusion",
    "small_mid_weakness",
    "turnover_concentration",
)


def score_bcd(inputs: BCDInput, *, source_fields: Mapping[str, str] | None = None) -> BCDResult:
    """Score BCD components without imputing missing data as neutral values."""

    component_scores: dict[str, float] = {}
    raw_inputs: dict[str, Any] = _raw_inputs(inputs)
    threshold_hits: dict[str, bool] = {}
    missing: list[str] = []
    sources = dict(source_fields or {})

    index_score, index_hits, index_missing = _score_index_breadth_divergence(inputs)
    _record_component("index_breadth_divergence", index_score, index_hits, index_missing, component_scores, threshold_hits, missing)

    main7_score, main7_hits, main7_missing = _score_main7_concentration(inputs)
    _record_component("main7_concentration", main7_score, main7_hits, main7_missing, component_scores, threshold_hits, missing)

    sector_score, sector_hits, sector_missing = _score_sector_diffusion(inputs)
    _record_component("sector_diffusion", sector_score, sector_hits, sector_missing, component_scores, threshold_hits, missing)

    smid_score, smid_hits, smid_missing = _score_small_mid_weakness(inputs)
    _record_component("small_mid_weakness", smid_score, smid_hits, smid_missing, component_scores, threshold_hits, missing)

    turnover_score, turnover_hits, turnover_missing = _score_turnover_concentration(inputs)
    _record_component("turnover_concentration", turnover_score, turnover_hits, turnover_missing, component_scores, threshold_hits, missing)

    final_score = round(sum(component_scores.values()), 4)
    missing_tuple = tuple(dict.fromkeys(missing))
    return BCDResult(
        final_score=final_score,
        component_scores=component_scores,
        raw_inputs=raw_inputs,
        threshold_hits=threshold_hits,
        missing_components=missing_tuple,
        source_fields=sources,
        data_quality_status="complete" if not missing_tuple else "partial",
    )


def _score_index_breadth_divergence(inputs: BCDInput) -> tuple[float | None, dict[str, bool], tuple[str, ...]]:
    missing: list[str] = []
    if inputs.advancing_issues < 0 or inputs.declining_issues < 0:
        missing.append("advancing_declining_issues")
    total = inputs.advancing_issues + inputs.declining_issues
    if total <= 0:
        missing.append("advancing_declining_issues")
    if missing:
        return None, {}, tuple(missing)

    advance_ratio = inputs.advancing_issues / total
    history_ratios = [bar.advance_ratio for bar in inputs.breadth_history if bar.advance_ratio is not None]
    history_mean = sum(history_ratios) / len(history_ratios) if history_ratios else None
    if history_mean is None:
        missing.append("breadth_history")

    hits = {
        "index_breadth_divergence.taiex_up": inputs.taiex_return_pct > 0,
        "index_breadth_divergence.advancing_ratio_below_45pct": advance_ratio < 0.45,
        "index_breadth_divergence.decliners_gt_advancers": inputs.declining_issues > inputs.advancing_issues,
        "index_breadth_divergence.below_history_mean_10pp": bool(history_mean is not None and advance_ratio < history_mean - 0.10),
    }
    score = 0.0
    if hits["index_breadth_divergence.taiex_up"]:
        if hits["index_breadth_divergence.decliners_gt_advancers"]:
            score += 9.0
        if hits["index_breadth_divergence.advancing_ratio_below_45pct"]:
            score += 6.0
        if hits["index_breadth_divergence.below_history_mean_10pp"]:
            score += 5.0
    elif inputs.taiex_return_pct <= 0 and inputs.declining_issues > inputs.advancing_issues * 1.5:
        score += 4.0
        hits["index_breadth_divergence.down_day_broad_weakness"] = True
    return min(20.0, score), hits, tuple(missing)


def _score_main7_concentration(inputs: BCDInput) -> tuple[float | None, dict[str, bool], tuple[str, ...]]:
    missing: list[str] = []
    if not inputs.main7_returns:
        missing.append("main7_returns")
    if not inputs.main7_weights:
        missing.append("main7_weights")
    total = inputs.advancing_issues + inputs.declining_issues
    if total <= 0:
        missing.append("advancing_declining_issues")
    if missing:
        return None, {}, tuple(missing)

    weighted = _weighted_average(inputs.main7_returns, inputs.main7_weights)
    advance_ratio = inputs.advancing_issues / total
    participation_weak = advance_ratio < 0.50 or inputs.declining_issues > inputs.advancing_issues
    hits = {
        "main7_concentration.main7_outperforms_taiex_1pp": weighted - inputs.taiex_return_pct >= 1.0,
        "main7_concentration.main7_positive_taiex_nonnegative": weighted > 0 and inputs.taiex_return_pct >= 0,
        "main7_concentration.broad_participation_weak": participation_weak,
    }
    score = 0.0
    if hits["main7_concentration.broad_participation_weak"] and hits["main7_concentration.main7_positive_taiex_nonnegative"]:
        score += 8.0
    if hits["main7_concentration.broad_participation_weak"] and hits["main7_concentration.main7_outperforms_taiex_1pp"]:
        score += 8.0
    if weighted >= 1.5 and participation_weak:
        score += 4.0
        hits["main7_concentration.main7_return_ge_1_5pct"] = True
    return min(20.0, score), hits, tuple(missing)


def _score_sector_diffusion(inputs: BCDInput) -> tuple[float | None, dict[str, bool], tuple[str, ...]]:
    if not inputs.sector_returns and not inputs.sector_above_ma20:
        return None, {}, ("sector_breadth",)
    hits: dict[str, bool] = {}
    score = 0.0
    if inputs.sector_returns:
        weak_ratio = sum(1 for value in inputs.sector_returns.values() if value <= 0) / len(inputs.sector_returns)
        hits["sector_diffusion.negative_return_majority"] = weak_ratio >= 0.60
        score += min(10.0, max(0.0, (weak_ratio - 0.40) / 0.60 * 10.0))
    else:
        return_missing = ("sector_returns",)
        weak_ratio = None
        hits["sector_diffusion.negative_return_majority"] = False
    if inputs.sector_above_ma20:
        below_ratio = sum(1 for value in inputs.sector_above_ma20.values() if not value) / len(inputs.sector_above_ma20)
        hits["sector_diffusion.below_ma20_majority"] = below_ratio >= 0.60
        score += min(10.0, max(0.0, (below_ratio - 0.40) / 0.60 * 10.0))
    else:
        return_missing = ("sector_above_ma20",) if inputs.sector_returns else ("sector_returns", "sector_above_ma20")
    return min(20.0, score), hits, return_missing if 'return_missing' in locals() else ()


def _score_small_mid_weakness(inputs: BCDInput) -> tuple[float | None, dict[str, bool], tuple[str, ...]]:
    missing: list[str] = []
    if inputs.otc_return_pct is None:
        missing.append("otc_return_pct")
    if inputs.small_mid_breadth is None:
        missing.append("small_mid_breadth")
    if missing:
        return None, {}, tuple(missing)
    assert inputs.otc_return_pct is not None
    assert inputs.small_mid_breadth is not None
    small_ratio = inputs.small_mid_breadth.advance_ratio
    if small_ratio is None:
        return None, {}, ("small_mid_breadth",)
    total = inputs.advancing_issues + inputs.declining_issues
    taiex_ratio = inputs.advancing_issues / total if total > 0 else None
    hits = {
        "small_mid_weakness.otc_underperforms_taiex_1pp": inputs.otc_return_pct <= inputs.taiex_return_pct - 1.0,
        "small_mid_weakness.small_mid_advancing_ratio_below_45pct": small_ratio < 0.45,
        "small_mid_weakness.small_mid_weaker_than_taiex_breadth_10pp": bool(taiex_ratio is not None and small_ratio < taiex_ratio - 0.10),
    }
    score = 0.0
    if hits["small_mid_weakness.otc_underperforms_taiex_1pp"]:
        score += 8.0
    if hits["small_mid_weakness.small_mid_advancing_ratio_below_45pct"]:
        score += 7.0
    if hits["small_mid_weakness.small_mid_weaker_than_taiex_breadth_10pp"]:
        score += 5.0
    return min(20.0, score), hits, ()


def _score_turnover_concentration(inputs: BCDInput) -> tuple[float | None, dict[str, bool], tuple[str, ...]]:
    missing: list[str] = []
    if inputs.turnover_concentration_topn is None:
        missing.append("turnover_concentration_topn")
    total = inputs.advancing_issues + inputs.declining_issues
    if total <= 0:
        missing.append("advancing_declining_issues")
    if missing:
        return None, {}, tuple(missing)
    assert inputs.turnover_concentration_topn is not None
    advance_ratio = inputs.advancing_issues / total
    broad_weak = advance_ratio < 0.50 or inputs.declining_issues > inputs.advancing_issues
    hits = {
        "turnover_concentration.topn_share_ge_35pct": inputs.turnover_concentration_topn >= 0.35,
        "turnover_concentration.topn_share_ge_50pct": inputs.turnover_concentration_topn >= 0.50,
        "turnover_concentration.broad_participation_weak": broad_weak,
    }
    score = 0.0
    if hits["turnover_concentration.topn_share_ge_35pct"] and broad_weak:
        score += 12.0
    if hits["turnover_concentration.topn_share_ge_50pct"] and broad_weak:
        score += 8.0
    return min(20.0, score), hits, ()


def _record_component(
    name: str,
    score: float | None,
    hits: Mapping[str, bool],
    missing: Sequence[str],
    component_scores: dict[str, float],
    threshold_hits: dict[str, bool],
    missing_components: list[str],
) -> None:
    if score is not None:
        component_scores[name] = round(score, 4)
        threshold_hits.update(hits)
    if missing:
        missing_components.extend(missing)
        if score is None:
            missing_components.append(name)


def _weighted_average(values: Mapping[str, float], weights: Mapping[str, float]) -> float:
    numerator = 0.0
    denominator = 0.0
    for symbol, value in values.items():
        weight = float(weights.get(symbol, 0.0))
        if not math.isfinite(weight) or weight <= 0:
            continue
        numerator += float(value) * weight
        denominator += weight
    if denominator <= 0:
        return sum(float(value) for value in values.values()) / len(values)
    return numerator / denominator


def _raw_inputs(inputs: BCDInput) -> dict[str, Any]:
    return {
        "taiex_return_pct": inputs.taiex_return_pct,
        "advancing_issues": inputs.advancing_issues,
        "declining_issues": inputs.declining_issues,
        "breadth_history": [bar.__dict__ for bar in inputs.breadth_history],
        "main7_returns": dict(inputs.main7_returns),
        "main7_weights": dict(inputs.main7_weights),
        "sector_returns": dict(inputs.sector_returns),
        "sector_above_ma20": dict(inputs.sector_above_ma20),
        "otc_return_pct": inputs.otc_return_pct,
        "small_mid_breadth": inputs.small_mid_breadth.__dict__ if inputs.small_mid_breadth else None,
        "turnover_concentration_topn": inputs.turnover_concentration_topn,
    }


__all__ = ["BreadthBar", "BCDInput", "BCDResult", "score_bcd"]
