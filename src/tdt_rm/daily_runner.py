"""Daily production runner for TDT-RM V5.1.4.

This module is intentionally a thin orchestration layer: it downloads public
TAIEX price bars, derives the minimum price features needed by the existing
V5.1.4 scoring modules, and writes daily JSON/Markdown artifacts.  It does not
change model scoring logic.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, fields
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .bcd import BCDInput, BCDResult, BreadthBar, assert_bcd_tail_risk_independence, score_bcd
from .crash_probability import CrashProbabilityInput, score_crash_probability
from .decision_matrix import (
    BearTrendInput,
    DecisionMatrixInput,
    score_bear_trend_filter,
    resolve_five_light_signal,
)
from .eti5 import ETI5Input, score_eti5
from .market_data import MarketPriceBar, derive_price_features
from .tcwrs import TCWRSInput, score_tcwrs
from .daily_snapshot import (
    DailyMarketSnapshot,
    build_source_coverage,
    derive_eti_available_components,
    load_daily_snapshot_json,
    snapshot_to_market_observation,
    validate_daily_snapshot,
)
from .daily_validation import build_daily_run_manifest, validate_daily_artifacts
from .report_quality import assess_production_report_quality, render_operator_disclosure

DEFAULT_OUTPUT_DIR = Path("outputs/daily")
DEFAULT_TWSE_URL = "https://www.twse.com.tw/rwd/en/TAIEX/MI_5MINS_HIST"
DEFAULT_MIN_BARS = 61
DEFAULT_LOOKBACK_MONTHS = 12
MODEL_VERSION = "TDT-RM V5.1.4"


class DailyDataFetcher(Protocol):
    """Protocol for future data vendors or ETF Exit-aware data fetchers."""

    def fetch_bars(self, *, as_of: date, min_bars: int) -> Sequence[MarketPriceBar]:
        """Return chronological Taiwan market bars ending at the latest available date."""


@dataclass(frozen=True)
class ETFExitHook:
    """Placeholder contract for future ETF Exit integration.

    The daily runner records this metadata today but does not apply ETF-specific
    exit logic.  Future integrations can replace this hook with a populated ETF
    exit result without changing the daily artifact shape.
    """

    enabled: bool = False
    status: str = "not_integrated"
    notes: str = "Reserved for future ETF Exit integration; no ETF exit logic applied."
    payload: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "status": self.status,
            "notes": self.notes,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class TWSETAIEXFetcher:
    """Download latest TAIEX index bars from the public TWSE monthly endpoint."""

    base_url: str = DEFAULT_TWSE_URL
    lookback_months: int = DEFAULT_LOOKBACK_MONTHS
    timeout_seconds: float = 20.0

    def fetch_bars(self, *, as_of: date, min_bars: int) -> Sequence[MarketPriceBar]:
        bars: dict[date, MarketPriceBar] = {}
        for month_start in _month_starts_desc(as_of, self.lookback_months):
            for bar in self._fetch_month(month_start):
                if _coerce_date(bar.observed_at) <= as_of:
                    bars[_coerce_date(bar.observed_at)] = bar
            if len(bars) >= min_bars and bars:
                latest = max(bars)
                oldest_needed = sorted(bars)[-min_bars]
                if oldest_needed <= latest:
                    break
        ordered = [bars[key] for key in sorted(bars)]
        if len(ordered) < min_bars:
            raise ValueError(
                f"TWSE download returned {len(ordered)} usable bars; at least {min_bars} are required"
            )
        return ordered[-min_bars:]

    def _fetch_month(self, month_start: date) -> Sequence[MarketPriceBar]:
        query = urllib.parse.urlencode(
            {"date": month_start.strftime("%Y%m%d"), "response": "json"}
        )
        request = urllib.request.Request(
            f"{self.base_url}?{query}",
            headers={"User-Agent": "TDT-RM daily runner"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8-sig"))
        return parse_twse_taiex_payload(payload)


@dataclass(frozen=True)
class DailyRunResult:
    """Paths and payload emitted by one daily production run."""

    json_path: Path
    markdown_path: Path
    payload: Mapping[str, Any]
    manifest_path: Path | None = None


def run_daily_production(
    *,
    as_of: date | None = None,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    fetcher: DailyDataFetcher | None = None,
    timestamp: datetime | None = None,
    etf_exit_hook: ETFExitHook | None = None,
    write_manifest: bool = False,
    command: str | None = None,
    git_sha: str | None = None,
    snapshot_path: str | Path | None = None,
    snapshot: DailyMarketSnapshot | None = None,
) -> DailyRunResult:
    """Download latest Taiwan market data or load a snapshot, run V5.1.4, and save artifacts."""

    if snapshot_path is not None and snapshot is not None:
        raise ValueError("provide either snapshot_path or snapshot, not both")
    run_timestamp = timestamp or datetime.now(UTC)
    effective_as_of = as_of or run_timestamp.date()
    if snapshot_path is not None or snapshot is not None:
        effective_snapshot = snapshot or load_daily_snapshot_json(snapshot_path)  # type: ignore[arg-type]
        snapshot_validation = validate_daily_snapshot(effective_snapshot, as_of=effective_as_of)
        if not snapshot_validation.is_valid:
            details = "; ".join(issue.message for issue in snapshot_validation.issues if issue.severity == "error")
            raise ValueError(f"daily snapshot validation failed: {details}")
        payload = build_daily_payload_from_snapshot(
            effective_snapshot,
            timestamp=run_timestamp,
            etf_exit_hook=etf_exit_hook or ETFExitHook(),
        )
    else:
        data_fetcher = fetcher or TWSETAIEXFetcher()
        bars = list(data_fetcher.fetch_bars(as_of=effective_as_of, min_bars=DEFAULT_MIN_BARS))
        if len(bars) < DEFAULT_MIN_BARS:
            raise ValueError(f"at least {DEFAULT_MIN_BARS} bars are required")

        payload = build_daily_payload(
            bars,
            timestamp=run_timestamp,
            etf_exit_hook=etf_exit_hook or ETFExitHook(),
        )
    payload = _payload_with_production_quality(payload)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    trade_date = payload["trade_date"]
    json_path = destination / f"tdt_rm_daily_{trade_date}.json"
    markdown_path = destination / f"tdt_rm_daily_{trade_date}.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_daily_markdown(payload), encoding="utf-8")

    manifest_path: Path | None = None
    if write_manifest:
        validation = validate_daily_artifacts(json_path, markdown_path, as_of=effective_as_of)
        manifest = build_daily_run_manifest(
            payload,
            json_path,
            markdown_path,
            command=command,
            git_sha=git_sha if git_sha is not None else _detect_git_sha(),
            validation=validation,
        )
        manifest_path = destination / f"tdt_rm_daily_{trade_date}_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return DailyRunResult(
        json_path=json_path,
        markdown_path=markdown_path,
        payload=payload,
        manifest_path=manifest_path,
    )


def build_daily_payload(
    bars: Sequence[MarketPriceBar],
    *,
    timestamp: datetime | None = None,
    etf_exit_hook: ETFExitHook | None = None,
) -> dict[str, Any]:
    """Run existing V5.1.4 modules against already-downloaded chronological bars."""

    if len(bars) < DEFAULT_MIN_BARS:
        raise ValueError(f"at least {DEFAULT_MIN_BARS} bars are required")
    ordered = sorted(bars, key=lambda bar: _coerce_date(bar.observed_at))
    features = derive_price_features(ordered)
    closes = [float(bar.close) for bar in ordered]
    close = float(features["close"])
    ma20 = float(features["ma20"])
    ma60 = float(features["ma60"])
    previous_ma60 = _moving_average(closes[:-1], 60)
    one_day_return = float(features["one_day_return_pct"])
    two_day_return = float(features["two_day_return_pct"])
    five_day_return = _pct_change(closes[-6], closes[-1]) if len(closes) >= 6 else 0.0
    return_60d = _pct_change(closes[-61], closes[-1]) if len(closes) >= 61 else 0.0
    consecutive_down_days = _consecutive_down_days(closes)
    close_below_ma20_days = _consecutive_below_ma20(closes)
    peak = max(closes)
    drawdown = max(0.0, -_pct_change(peak, close))
    tail_risk = _price_proxy_tail_risk(closes, drawdown, one_day_return, two_day_return)
    bcd_result = _price_only_bcd_result(one_day_return)
    bcd = bcd_result.final_score
    mhs = 0.0

    tcwrs = score_tcwrs(
        TCWRSInput(
            close=close,
            ma5=float(features["ma5"]),
            ma20=ma20,
            ma60=ma60,
            ma20_slope=float(features["ma20_slope"]),
            close_below_ma20_consecutive_days=close_below_ma20_days,
            one_day_return_pct=one_day_return,
            two_day_return_pct=two_day_return,
            close_is_black=one_day_return < -1.5,
            long_black_candle=one_day_return < -2.0,
            index_5d_return_pct=five_day_return,
            margin_balance_5d_decline_pct=max(0.0, -five_day_return / 2.0),
            index_down=one_day_return < 0,
            declining_issues_significantly_expand=one_day_return < -1.5,
            declining_issues_significantly_gt_advancing=one_day_return < -0.75,
            declining_gt_advancing_consecutive_days=consecutive_down_days,
            count_main_7_below_ma20=5 if close < ma20 else 0,
        )
    )
    eti5 = score_eti5(
        ETI5Input(
            close=close,
            ma20=ma20,
            available_components={"ETI-1"},
        )
    )
    cp = score_crash_probability(
        CrashProbabilityInput(
            tcwrs=tcwrs.total_score,
            eti5_total=eti5.eti_score,
            tail_risk=tail_risk,
            bcd=bcd,
            bcd_status=bcd_result.data_quality_status,
        )
    )
    bear_trend = score_bear_trend_filter(
        BearTrendInput(
            close=close,
            ma20=ma20,
            ma60=ma60,
            previous_ma60=previous_ma60,
            return_60d_pct=return_60d,
        )
    )
    decision = resolve_five_light_signal(
        DecisionMatrixInput(
            tcwrs=tcwrs.total_score,
            eti5_total=eti5.eti_score,
            tail_risk=tail_risk,
            bcd=bcd,
            taiex=close,
            bcd_status=bcd_result.data_quality_status,
            ma20=ma20,
            consecutive_down_days=consecutive_down_days,
            mhs=mhs,
            cp_score=cp.cp_score,
            eti_available_count=eti5.eti_available_count,
        ),
        bear_trend=bear_trend,
    )
    market_regime = classify_market_regime(decision.signal, tcwrs.total_score, close, ma20, ma60)
    run_timestamp = timestamp or datetime.now(UTC)
    etf_hook = etf_exit_hook or ETFExitHook()

    return {
        "timestamp": _iso_timestamp(run_timestamp),
        "model_version": MODEL_VERSION,
        "trade_date": str(features["observed_at"]),
        "market_regime": market_regime,
        "tcwrs": tcwrs.total_score,
        "mhs": mhs,
        "eti_5": eti5.eti_score,
        "tail_risk": round(tail_risk, 2),
        "bcd": _round_optional(bcd),
        "bcd_status": bcd_result.data_quality_status,
        "bcd_data_completeness": bcd_result.data_completeness,
        "bcd_missing_components": list(bcd_result.missing_components),
        "bcd_source_dependencies": list(bcd_result.source_dependencies),
        "bcd_calculation_version": bcd_result.calculation_version,
        "cp": round(cp.cp_score, 2),
        "cp_level": cp.cp_level,
        "signal": decision.signal,
        "equity_exposure_limit": decision.equity_exposure_limit,
        "inputs": {
            "close": round(close, 2),
            "ma5": round(float(features["ma5"]), 2),
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2),
            "ma20_slope": round(float(features["ma20_slope"]), 4),
            "one_day_return_pct": round(one_day_return, 4),
            "two_day_return_pct": round(two_day_return, 4),
            "five_day_return_pct": round(five_day_return, 4),
            "return_60d_pct": round(return_60d, 4),
            "consecutive_down_days": consecutive_down_days,
            "close_below_ma20_consecutive_days": close_below_ma20_days,
        },
        "scores": {
            "TCWRS": tcwrs.total_score,
            "MHS": mhs,
            "ETI-5": eti5.eti_score,
            "Tail Risk": round(tail_risk, 2),
            "BCD": _round_optional(bcd),
            "CP": round(cp.cp_score, 2),
        },
        "traces": {
            "tcwrs": tcwrs.as_dict(),
            "eti_5": eti5.as_dict(),
            "crash_probability": cp.as_dict(),
            "bear_trend": bear_trend.as_dict(),
            "decision_matrix": decision.as_dict(),
            "bcd": bcd_result.as_dict(),
        },
        "data": {
            "source": "TWSE TAIEX MI_5MINS_HIST public monthly index endpoint",
            "latest_bar_date": str(features["observed_at"]),
            "bar_count": len(ordered),
            "status": "price_only_provisional",
            "limitations": [
                "ETI-5 is limited to the available ETI-1 price component.",
                "BCD is INCOMPLETE and null: price-only run lacks required independent BCD inputs; no Tail Risk/options proxy is used.",
                "MHS has no standalone scorer in this repository and is set to 0.0.",
            ],
        },
        "etf_exit": etf_hook.as_dict(),
    }


def build_daily_payload_from_snapshot(
    snapshot: DailyMarketSnapshot,
    *,
    timestamp: datetime | None = None,
    etf_exit_hook: ETFExitHook | None = None,
) -> dict[str, Any]:
    """Run existing V5.1.4 modules against an enriched canonical daily snapshot."""

    validation = validate_daily_snapshot(snapshot)
    if not validation.is_valid:
        details = "; ".join(issue.message for issue in validation.issues if issue.severity == "error")
        raise ValueError(f"daily snapshot validation failed: {details}")
    observation = snapshot_to_market_observation(snapshot)
    coverage = build_source_coverage(snapshot)
    available_components = derive_eti_available_components(snapshot)
    tcwrs = score_tcwrs(observation.tcwrs_input)
    global_risk_unavailable_fields = _unavailable_global_risk_fields(snapshot)
    eti_input = observation.eti5_input or ETI5Input(
        close=observation.tcwrs_input.close,
        ma20=observation.tcwrs_input.ma20,
    )
    eti_input = _eti_input_with_available_components(eti_input, available_components)
    eti5 = score_eti5(eti_input)

    proxy_info: dict[str, Any] = {}
    closes = [float(bar.close) for bar in sorted(snapshot.price_bars, key=lambda bar: _coerce_date(bar.observed_at))]
    close = float(observation.tcwrs_input.close)
    ma20 = float(observation.tcwrs_input.ma20)
    ma60 = float(observation.tcwrs_input.ma60)
    one_day_return = float(observation.tcwrs_input.one_day_return_pct)
    two_day_return = float(observation.tcwrs_input.two_day_return_pct)
    consecutive_down_days = int(observation.tcwrs_input.declining_gt_advancing_consecutive_days)
    if closes:
        peak = max(closes)
        drawdown = max(0.0, -_pct_change(peak, close))
        consecutive_down_days = _consecutive_down_days(closes)
    else:
        drawdown = max(0.0, (ma20 - close) / ma20 * 100.0) if ma20 else 0.0

    if observation.tail_risk is None:
        source_closes = closes if len(closes) >= 2 else [close, close]
        tail_risk = _price_proxy_tail_risk(source_closes, drawdown, one_day_return, two_day_return)
        proxy_info["tail_risk"] = {
            "status": "price_only_proxy",
            "reason": "formal tail_risk absent from daily snapshot",
        }
    else:
        tail_risk = float(observation.tail_risk)
    bcd_result = _bcd_result_from_snapshot(snapshot, taiex_return_pct=one_day_return)
    bcd = bcd_result.final_score
    if bcd_result.data_quality_status != "COMPLETE":
        proxy_info["bcd"] = {
            "status": "incomplete_bcd",
            "reason": "Required independent BCD inputs are incomplete; BCD is null and no proxy is used",
            "missing_components": list(bcd_result.missing_components),
        }

    mhs = float(snapshot.canonical_row.get("mhs", 0.0) or 0.0)
    previous_ma60 = _previous_ma60_from_snapshot(snapshot, ma60)
    return_60d = _return_60d_from_snapshot(snapshot, close)
    five_day_return = float(observation.tcwrs_input.index_5d_return_pct)
    close_below_ma20_days = int(observation.tcwrs_input.close_below_ma20_consecutive_days)

    cp = score_crash_probability(
        CrashProbabilityInput(
            tcwrs=tcwrs.total_score,
            eti5_total=eti5.eti_score,
            tail_risk=tail_risk,
            bcd=bcd,
            bcd_status=bcd_result.data_quality_status,
        )
    )
    bear_trend = score_bear_trend_filter(
        BearTrendInput(
            close=close,
            ma20=ma20,
            ma60=ma60,
            previous_ma60=previous_ma60,
            return_60d_pct=return_60d,
        )
    )
    decision = resolve_five_light_signal(
        DecisionMatrixInput(
            tcwrs=tcwrs.total_score,
            eti5_total=eti5.eti_score,
            tail_risk=tail_risk,
            bcd=bcd,
            taiex=close,
            ma20=ma20,
            bcd_status=bcd_result.data_quality_status,
            consecutive_down_days=consecutive_down_days,
            mhs=mhs,
            cp_score=cp.cp_score,
            eti_available_count=eti5.eti_available_count,
        ),
        bear_trend=bear_trend,
    )
    market_regime = classify_market_regime(decision.signal, tcwrs.total_score, close, ma20, ma60)
    run_timestamp = timestamp or datetime.now(UTC)
    etf_hook = etf_exit_hook or ETFExitHook()
    latest_bar_date = str(_coerce_date(snapshot.price_bars[-1].observed_at)) if snapshot.price_bars else str(snapshot.trade_date)
    limitations = list(snapshot.limitations)
    limitations.append("MHS uses snapshot field mhs when supplied; no formal MHS scorer is implemented.")
    if "tail_risk" in proxy_info:
        limitations.append("Tail Risk uses a documented price-only fallback because formal snapshot values are absent.")
    if "bcd" in proxy_info:
        limitations.append("BCD is INCOMPLETE and null when required independent inputs are missing; no Tail Risk/options proxy is used.")
    _assert_snapshot_bcd_tail_risk_independence(snapshot, bcd, tail_risk)

    return {
        "timestamp": _iso_timestamp(run_timestamp),
        "model_version": MODEL_VERSION,
        "trade_date": str(snapshot.trade_date),
        "market_regime": market_regime,
        "tcwrs": tcwrs.total_score,
        "mhs": mhs,
        "eti_5": eti5.eti_score,
        "tail_risk": round(tail_risk, 2),
        "bcd": _round_optional(bcd),
        "bcd_status": bcd_result.data_quality_status,
        "bcd_data_completeness": bcd_result.data_completeness,
        "bcd_missing_components": list(bcd_result.missing_components),
        "bcd_source_dependencies": list(bcd_result.source_dependencies),
        "bcd_calculation_version": bcd_result.calculation_version,
        "cp": round(cp.cp_score, 2),
        "cp_level": cp.cp_level,
        "signal": decision.signal,
        "equity_exposure_limit": decision.equity_exposure_limit,
        "inputs": {
            "close": round(close, 2),
            "ma5": round(float(observation.tcwrs_input.ma5), 2),
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2),
            "ma20_slope": round(float(observation.tcwrs_input.ma20_slope), 4),
            "one_day_return_pct": round(one_day_return, 4),
            "two_day_return_pct": round(two_day_return, 4),
            "five_day_return_pct": round(five_day_return, 4),
            "return_60d_pct": round(return_60d, 4),
            "consecutive_down_days": consecutive_down_days,
            "close_below_ma20_consecutive_days": close_below_ma20_days,
        },
        "scores": {
            "TCWRS": tcwrs.total_score,
            "MHS": mhs,
            "ETI-5": eti5.eti_score,
            "Tail Risk": round(tail_risk, 2),
            "BCD": _round_optional(bcd),
            "CP": round(cp.cp_score, 2),
        },
        "traces": {
            "tcwrs": tcwrs.as_dict(),
            "eti_5": eti5.as_dict(),
            "crash_probability": cp.as_dict(),
            "bear_trend": bear_trend.as_dict(),
            "decision_matrix": decision.as_dict(),
            "bcd": bcd_result.as_dict(),
        },
        "data": {
            "source": "Daily enriched market snapshot",
            "latest_bar_date": latest_bar_date,
            "bar_count": len(snapshot.price_bars) if snapshot.price_bars else DEFAULT_MIN_BARS,
            "status": snapshot.data_status,
            "limitations": limitations,
            "warnings": list(snapshot.warnings),
            "fallback_proxies": proxy_info,
            "field_sources": {key: value.as_dict() for key, value in coverage.field_sources.items()},
            "source_metadata": {key: dict(value) for key, value in snapshot.source_metadata.items()},
            "missing_fields": list(coverage.missing_fields),
            "available_eti_components": list(coverage.available_eti_components),
            "data_status": coverage.data_status,
            "snapshot_validation": validation.as_dict(),
            "unavailable_global_risk_fields": global_risk_unavailable_fields,
            "global_risk_calculation_status": (
                "unavailable_source_fields_excluded" if global_risk_unavailable_fields else "confirmed_source_fields"
            ),
        },
        "etf_exit": etf_hook.as_dict(),
    }



def _round_optional(value: float | None, ndigits: int = 2) -> float | None:
    return None if value is None else round(float(value), ndigits)


def _assert_snapshot_bcd_tail_risk_independence(snapshot: DailyMarketSnapshot, bcd: float | None, tail_risk: float) -> None:
    raw_history = snapshot.canonical_row.get("bcd_tail_risk_history") or snapshot.canonical_row.get("bcd_tail_risk_comparison_history")
    rows: list[Mapping[str, Any]] = []
    if isinstance(raw_history, str) and raw_history.strip():
        try:
            raw_history = json.loads(raw_history)
        except json.JSONDecodeError:
            raw_history = []
    if isinstance(raw_history, Sequence) and not isinstance(raw_history, (str, bytes)):
        rows.extend(item for item in raw_history if isinstance(item, Mapping))
    rows.append({"trade_date": snapshot.trade_date.isoformat(), "bcd": bcd, "tail_risk": tail_risk})
    assert_bcd_tail_risk_independence(rows)


def _unavailable_global_risk_fields(snapshot: DailyMarketSnapshot) -> list[str]:
    """Return global-risk fields that are intentionally unavailable, not defaults.

    Nasdaq and SOX are optional external-pressure inputs.  When no provider
    source supplies them, keep the run non-blocking but disclose that those
    operator-facing global-risk values are unavailable rather than treating
    TCWRS dataclass defaults as confirmed market data.
    """

    row = dict(snapshot.canonical_row)
    unavailable: list[str] = []
    for field in ("nasdaq", "sox"):
        if field not in snapshot.field_sources and field not in row:
            unavailable.append(field)
    return unavailable


def _eti_input_with_available_components(data: ETI5Input, available_components: set[str]) -> ETI5Input:
    values = {field.name: getattr(data, field.name) for field in fields(ETI5Input)}
    values["available_components"] = set(available_components)
    return ETI5Input(**values)


def _previous_ma60_from_snapshot(snapshot: DailyMarketSnapshot, default_ma60: float) -> float:
    bars = sorted(snapshot.price_bars, key=lambda bar: _coerce_date(bar.observed_at))
    if len(bars) >= 61:
        return _moving_average([float(bar.close) for bar in bars[:-1]], 60)
    return float(snapshot.canonical_row.get("previous_ma60", default_ma60) or default_ma60)


def _return_60d_from_snapshot(snapshot: DailyMarketSnapshot, close: float) -> float:
    bars = sorted(snapshot.price_bars, key=lambda bar: _coerce_date(bar.observed_at))
    if len(bars) >= 61:
        return _pct_change(float(bars[-61].close), close)
    return float(snapshot.canonical_row.get("return_60d_pct", 0.0) or 0.0)


def render_daily_markdown(payload: Mapping[str, Any]) -> str:
    """Render the daily JSON payload as Dr. Yen's user-facing risk report."""

    return render_user_daily_report(payload)


def render_user_daily_report(payload: Mapping[str, Any], *, generated_at: str | datetime | None = None) -> str:
    """Render the final human-readable daily investment risk-control report."""

    scores = _mapping(payload.get("scores"))
    data = _mapping(payload.get("data"))
    trade_date = str(payload.get("trade_date") or data.get("latest_bar_date") or "")
    signal = str(payload.get("signal") or "")
    market_state = str(payload.get("market_regime") or payload.get("regime_state") or "watch")
    exposure_limit = payload.get("equity_exposure_limit") or payload.get("exposure_limit")
    report_time = _display_report_time(generated_at or payload.get("timestamp") or datetime.now(UTC))
    data_status = _display_data_status(data.get("data_status") or data.get("status") or payload.get("data_status"))
    tcwrs = scores.get("TCWRS", payload.get("tcwrs"))
    mhs = scores.get("MHS", payload.get("mhs"))
    eti5 = scores.get("ETI-5", payload.get("eti_5"))
    tail_risk = scores.get("Tail Risk", payload.get("tail_risk"))
    bcd = scores.get("BCD", payload.get("bcd"))
    cp = scores.get("CP", payload.get("cp"))
    eti_items = _eti_detail_lines(payload)
    yellow_tone = _normalized_signal(signal) == "yellow"

    lines = [
        f"{_slash_date(trade_date)} 台股雙溫度計風控報告",
        "作者：Dr. Yen",
        "模型：TDT-RM V5.1.4 Backtest Calibration Patch",
        f"資料日期：{_slash_date(trade_date)}",
        f"產出時間：{report_time}",
        f"資料狀態：{data_status}",
        "今日燈號：" + _display_signal(signal),
        "市場狀態：" + _display_market_state(market_state),
        f"TCWRS：{_format_value(tcwrs)}",
        f"MHS：{_format_value(mhs)}",
        f"ETI-5：{_format_value(eti5)}",
        f"Tail Risk：{_format_value(tail_risk)}",
        f"BCD：{_format_bcd_value(bcd, payload)}",
        *_bcd_short_disclosure_lines(payload),
        f"Crash Probability：{_format_probability(cp)}",
        f"股票曝險上限：{_display_exposure_limit(exposure_limit)}",
        "",
        "■ 核心結論",
        f"１、MHS{_heat_language(mhs)}，{_heat_meaning(mhs)}",
        f"２、TCWRS{_structure_language(tcwrs)}，代表目前結構性破壞{_structure_result(tcwrs)}。",
        f"３、ETI-5為{_format_value(eti5)}，{_eti_summary_language(eti5)}",
        f"４、{_mhs_reason_summary(mhs, payload)}",
        f"５、{_tail_risk_reason_summary(tail_risk, payload)}",
        f"６、今日操作應以{('持有、停止追價、不使用槓桿、等待風險是否擴散' if yellow_tone else _action_phrase(signal))}為主。",
        "",
        "■ ETI-5 明細",
        *eti_items,
        "",
        "■ 今日動作",
        "１、持股：維持核心持股，單日不因高檔震盪而情緒化出清。",
        f"２、加碼：{('暫停追高，等待拉回或風險指標降溫' if yellow_tone else '僅在符合原有配置紀律時小幅執行')}。",
        f"３、減碼：{_de_risk_action(signal)}",
        f"４、槓桿：{('不融資、不加槓桿' if yellow_tone else '不新增槓桿，既有槓桿需受曝險上限約束')}。",
        f"５、現金部位：保留調節空間，使股票曝險不高於{_display_exposure_limit(exposure_limit)}。",
        "",
        "■ 優先減碼順序",
        f"目前{_forced_de_risk_sentence(signal)}；若後續升燈，減碼順序如下：",
        "１、高波動科技ETF或主題ETF",
        "２、短線追高部位",
        "３、槓桿或融資部位",
        "４、核心長期ETF",
        "",
        "■ 警報解除條件",
        "１、MHS降溫。",
        "２、TCWRS維持低檔。",
        "３、ETI-5降至0或1。",
        "４、Tail Risk未升高。",
        "５、BCD未出現明顯假強勢。",
        "",
        "■ 結論",
        _investment_conclusion(signal, tcwrs, mhs, eti5),
        "",
    ]
    return "\n".join(lines)


def _slash_date(value: Any) -> str:
    text = str(value or "")[:10]
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text.replace("-", "/")
    return text


def _display_report_time(value: str | datetime) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y/%m/%d %H:%M")
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return str(value)[:16].replace("-", "/").replace("T", " ")
    return parsed.strftime("%Y/%m/%d %H:%M")


def _display_data_status(value: Any) -> str:
    normalized = str(value or "").lower()
    if normalized in {"official", "formal", "final", "passed", "enriched_snapshot"}:
        return "正式版"
    return "暫估版"


def _normalized_signal(value: Any) -> str:
    return str(value or "").strip().lower()


def _display_signal(value: Any) -> str:
    return {"green": "綠燈", "yellow": "黃燈", "strengthened yellow": "強化黃燈", "orange": "橘燈", "red": "紅燈", "deep red": "紅燈"}.get(_normalized_signal(value), str(value or "未定"))


def _display_market_state(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return {"risk-on": "多頭偏強", "watch": "觀察", "caution": "謹慎", "risk-off": "風險收縮", "crash-risk": "崩跌風險", "hot": "高檔偏熱"}.get(normalized, str(value or "觀察"))


def _format_value(value: Any) -> str:
    if value is None:
        return "資料不足"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _display_exposure_limit(value: Any) -> str:
    text = str(value or "")
    return text.replace("60-80%", "60–80%")


def _format_bcd_value(value: Any, payload: Mapping[str, Any]) -> str:
    if value is not None:
        return _format_value(value)
    status = _bcd_status(payload)
    return f"資料不足／{status}" if status else "資料不足"


def _bcd_status(payload: Mapping[str, Any]) -> str:
    trace = _mapping(_mapping(payload.get("traces")).get("bcd"))
    status = str(payload.get("bcd_status") or trace.get("bcd_status") or trace.get("data_quality_status") or "INCOMPLETE").strip()
    return status or "INCOMPLETE"


def _bcd_short_disclosure_lines(payload: Mapping[str, Any]) -> list[str]:
    if _format_bcd_value(_mapping(payload.get("scores")).get("BCD", payload.get("bcd")), payload).startswith("資料不足"):
        return ["BCD 資料不足，未納入升燈判斷，不影響 TCWRS、ETI-5、Tail Risk 與今日燈號。"]
    return []


def _mhs_reason_summary(value: Any, payload: Mapping[str, Any]) -> str:
    trace = _mapping(_mapping(payload.get("traces")).get("mhs"))
    components = trace.get("components") or trace.get("component_scores")
    if not components:
        return "MHS 分項資料未完整揭露，因此僅能判定為市場過熱訊號，不可單獨解讀為崩盤風險。"
    return "MHS 升高代表情緒與動能偏熱，需搭配 TCWRS、ETI-5 與 Tail Risk 判讀，不可單獨解讀為崩盤風險。"


def _tail_risk_reason_summary(value: Any, payload: Mapping[str, Any]) -> str:
    trace = _mapping(_mapping(payload.get("traces")).get("tail_risk"))
    components = trace.get("components") or trace.get("component_scores")
    number = _number(value)
    if not components and number is not None and 40 <= number < 70:
        return "Tail Risk 為中度偏高，但尚未達高風險區，不能單獨升燈。"
    if number is not None and number >= 70:
        return "Tail Risk 已進入高風險區，需等待其他風控指標共同確認是否升燈。"
    return "Tail Risk 尚未形成可單獨升燈的極端尾部風險訊號。"


def _format_probability(value: Any) -> str:
    if value is None:
        return "資料不足"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number <= 1:
        number *= 100
    return f"{number:.2f}%".rstrip("0").rstrip(".") + "%" if False else f"{number:g}%"


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _heat_language(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "資料不足"
    if number >= 80:
        return "達高檔過熱區"
    if number >= 60:
        return "偏熱"
    return "尚未過熱"



def _heat_meaning(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "代表情緒溫度仍需補齊資料後判斷。"
    if number >= 60:
        return "代表市場情緒與價格動能偏熱；這是過熱提醒，不等於崩盤訊號。"
    return "代表市場情緒與價格動能尚未過熱，短線風險主要仍看結構指標是否轉弱。"

def _structure_language(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "資料不足"
    if number >= 60:
        return "升高"
    if number >= 30:
        return "中等"
    return "仍低"


def _structure_result(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "仍需觀察"
    if number >= 60:
        return "已明顯升高"
    if number >= 30:
        return "開始浮現但尚未全面確認"
    return "尚未明確出現"


def _eti_summary_language(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "代表早期警訊資料仍不完整。"
    if number <= 1:
        return "僅有早期警訊，表示風險尚未全面落地。"
    if number <= 3:
        return "代表風險正在擴散，需降低追價與槓桿。"
    return "代表多項風險同步觸發，應優先控管曝險。"


def _action_phrase(signal: Any) -> str:
    normalized = _normalized_signal(signal)
    if normalized in {"orange", "red", "deep red"}:
        return "降低曝險、保留現金、不新增風險部位"
    if normalized == "green":
        return "依計畫持有、避免過度集中"
    return "持有、不追高、不使用槓桿"


def _de_risk_action(signal: Any) -> str:
    normalized = _normalized_signal(signal)
    if normalized in {"orange", "red", "deep red"}:
        return "依升燈規則分批降低高波動與槓桿部位。"
    return "目前不需要強制減碼，但不應新增短線追高部位。"



def _bcd_status_disclosure_lines(payload: Mapping[str, Any]) -> list[str]:
    trace = _mapping(_mapping(payload.get("traces")).get("bcd"))
    status = str(payload.get("bcd_status") or trace.get("bcd_status") or trace.get("data_quality_status") or "INCOMPLETE")
    missing = payload.get("bcd_missing_components") or trace.get("bcd_missing_components") or trace.get("missing_components") or []
    if not isinstance(missing, Sequence) or isinstance(missing, (str, bytes)):
        missing = []
    return [
        f"BCD Status: {status}",
        "Missing Inputs: " + json.dumps([str(item) for item in missing], ensure_ascii=False),
    ]


def _forced_de_risk_sentence(signal: Any) -> str:
    return "不需要強制減碼" if _normalized_signal(signal) not in {"orange", "red", "deep red"} else "需要依規則分批減碼"


def _eti_detail_lines(payload: Mapping[str, Any]) -> list[str]:
    trace = _mapping(_mapping(payload.get("traces")).get("eti_5"))
    trace_output = _mapping(trace.get("trace_output"))
    labels = [
        ("ETI-1", "ETI-1 加權指數跌破20日線", "指數仍守在短期均線附近，價格結構尚未破壞。", "指數跌破20日線，短線價格結構轉弱。"),
        ("ETI-2", "ETI-2 外資連續賣超", "外資賣壓尚未形成連續確認。", "外資賣超延續，籌碼壓力升高。"),
        ("ETI-3", "ETI-3 新台幣轉貶", "匯率尚未出現明確資金外流壓力。", "新台幣轉貶，資金面壓力升高。"),
        ("ETI-4", "ETI-4 市場廣度惡化", "市場廣度尚未全面轉弱。", "市場廣度惡化，上漲結構變窄。"),
        ("ETI-5", "ETI-5 主流七標的失靈", "主流族群尚未同步失靈。", "主流標的轉弱，多頭領導力下降。"),
    ]
    lines: list[str] = []
    for index, (code, label, normal_text, triggered_text) in enumerate(labels, start=1):
        item = _mapping(trace_output.get(code))
        if item and item.get("available") is False:
            status = "資料不足"
            explanation = "該項資料不足，暫不視為確認警訊。"
        elif item:
            triggered = bool(item.get("triggered") or _number(item.get("score")) and _number(item.get("score")) > 0)
            status = "觸發" if triggered else "未觸發"
            explanation = triggered_text if triggered else normal_text
        else:
            status = "資料不足"
            explanation = "缺少足夠明細，暫以資料不足處理。"
        lines.append(f"{_FULLWIDTH_NUMBERS[index]}、{label}：{status}，{explanation}")
    return lines


_FULLWIDTH_NUMBERS = {1: "１", 2: "２", 3: "３", 4: "４", 5: "５"}


def _investment_conclusion(signal: Any, tcwrs: Any, mhs: Any, eti5: Any) -> str:
    if _normalized_signal(signal) in {"orange", "red", "deep red"}:
        return "目前市場已從單純過熱轉向風險擴散，操作重點不是預測最低點，而是先降低高波動、追高與槓桿部位，讓整體曝險回到可承受範圍。後續只有在價格結構修復、早期警訊下降且情緒降溫後，才適合重新提高風險部位。"
    return "目前市場屬於強勢多頭後期的偏熱狀態，而不是結構性崩盤狀態。操作上應維持核心持股，但停止追價與槓桿，等待TCWRS與ETI-5是否同步升高。真正需要大幅降曝險的條件，是價格破壞、外資賣超、台幣轉貶與主流股失靈同時出現。"




def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}

def _payload_with_production_quality(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Attach operator QC disclosure without changing model outputs."""

    enriched = dict(payload)
    quality = assess_production_report_quality(enriched)
    enriched["production_report_quality"] = quality["production_report_quality"]
    enriched["operator_disclosure"] = quality
    return enriched

def parse_twse_taiex_payload(payload: Mapping[str, Any]) -> list[MarketPriceBar]:
    """Parse TWSE MI_5MINS_HIST JSON payload into chronological price bars."""

    rows = payload.get("data") or payload.get("tables", [{}])[0].get("data") or []
    fields = [str(field).strip().lower() for field in payload.get("fields", [])]
    parsed: list[MarketPriceBar] = []
    for row in rows:
        values = list(row)
        if len(values) < 2:
            continue
        observed_at = _parse_twse_date(_field_value(values, fields, "date", 0))
        close = _parse_number(_field_value(values, fields, "closing index", -1))
        open_value = _optional_number(_field_value(values, fields, "opening index", 1))
        high = _optional_number(_field_value(values, fields, "highest index", 2))
        low = _optional_number(_field_value(values, fields, "lowest index", 3))
        parsed.append(
            MarketPriceBar(
                observed_at=observed_at,
                close=close,
                turnover_amount=0.0,
                open=open_value,
                high=high,
                low=low,
            )
        )
    return sorted(parsed, key=lambda bar: _coerce_date(bar.observed_at))


def classify_market_regime(signal: str, tcwrs: float, close: float, ma20: float, ma60: float) -> str:
    """Return a stable high-level label for daily reports without changing signals."""

    if signal == "Red" or tcwrs >= 76:
        return "crash-risk"
    if signal == "Orange" or close < ma60:
        return "risk-off"
    if signal == "Strengthened Yellow" or close < ma20:
        return "caution"
    if signal == "Yellow" or close < ma20 * 1.01:
        return "watch"
    return "risk-on"


def _price_proxy_tail_risk(
    closes: Sequence[float], drawdown: float, one_day_return: float, two_day_return: float
) -> float:
    twenty_returns = [
        _pct_change(closes[index - 1], closes[index])
        for index in range(max(1, len(closes) - 19), len(closes))
    ]
    volatility = statistics.pstdev(twenty_returns) if len(twenty_returns) > 1 else 0.0
    return min(100.0, max(drawdown * 2.5, volatility * 18.0, abs(min(one_day_return, two_day_return)) * 9.0))


def _price_proxy_bcd(close: float, ma20: float, drawdown: float, consecutive_down_days: int) -> float:
    below_ma20_pressure = max(0.0, (ma20 - close) / ma20 * 500.0) if ma20 else 0.0
    return min(100.0, max(drawdown * 2.0, below_ma20_pressure, consecutive_down_days * 12.0))



def _price_only_bcd_result(taiex_return_pct: float) -> BCDResult:
    return score_bcd(
        BCDInput(
            taiex_return_pct=taiex_return_pct,
            advancing_issues=0,
            declining_issues=0,
            breadth_history=(),
            main7_returns={},
            main7_weights={},
            sector_returns={},
            sector_above_ma20={},
            otc_return_pct=None,
            small_mid_breadth=None,
            turnover_concentration_topn=None,
        ),
        source_fields={"taiex_return_pct": "price.one_day_return_pct"},
    )


def _bcd_result_from_snapshot(snapshot: DailyMarketSnapshot, *, taiex_return_pct: float) -> BCDResult:
    row = dict(snapshot.canonical_row)
    source_fields = {name: snapshot.field_sources.get(name, "unavailable") for name in row}
    source_fields.setdefault("taiex_return_pct", snapshot.field_sources.get("one_day_return_pct", "price.one_day_return_pct"))
    return score_bcd(
        BCDInput(
            taiex_return_pct=taiex_return_pct,
            advancing_issues=_int_or_zero(row.get("advancing_issues")),
            declining_issues=_int_or_zero(row.get("declining_issues")),
            breadth_history=_breadth_history_from_row(row),
            main7_returns=_mapping_of_float(row.get("main7_returns") or row.get("main_7_returns")),
            main7_weights=_mapping_of_float(row.get("main7_weights") or row.get("main_7_weights")),
            sector_returns=_mapping_of_float(row.get("sector_returns")),
            sector_above_ma20=_mapping_of_bool(row.get("sector_above_ma20")),
            otc_return_pct=_optional_number(row.get("otc_return_pct")),
            small_mid_breadth=_small_mid_breadth_from_row(row),
            turnover_concentration_topn=_optional_number(row.get("turnover_concentration_topn") or row.get("topn_turnover_concentration")),
        ),
        source_fields=source_fields,
    )


def write_bcd_audit_artifacts(payload: Mapping[str, Any], output_dir: str | Path) -> dict[str, Path]:
    """Write JSON/CSV audit traces for the BCD module."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    trade_date = str(payload.get("trade_date") or "")
    trace = dict(_mapping(_mapping(payload.get("traces")).get("bcd")))
    trace.setdefault("final_score", payload.get("bcd"))
    trace.setdefault("component_scores", {})
    trace.setdefault("raw_inputs", {})
    trace.setdefault("threshold_hits", {})
    trace.setdefault("missing_components", [])
    trace.setdefault("source_fields", {})
    trace.setdefault("data_quality_status", "unavailable" if not trace.get("component_scores") else "partial")
    json_path = destination / "bcd_audit_trace.json"
    csv_path = destination / "bcd_audit_trace.csv"
    json_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    component_scores = _mapping(trace.get("component_scores"))
    raw_inputs = _mapping(trace.get("raw_inputs"))
    threshold_hits = _mapping(trace.get("threshold_hits"))
    source_fields = _mapping(trace.get("source_fields"))
    missing = {str(item) for item in trace.get("missing_components", []) or []}
    thresholds = _bcd_threshold_descriptions()
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("trade_date", "component", "raw_value", "threshold", "threshold_hit", "score", "source_field", "missing_reason"),
        )
        writer.writeheader()
        components = set(component_scores) | {item.split(".", 1)[0] for item in threshold_hits} | set(missing)
        for component in sorted(components):
            component_hits = {key: value for key, value in threshold_hits.items() if str(key).startswith(component + ".")}
            raw_value = _bcd_component_raw_value(component, raw_inputs)
            writer.writerow(
                {
                    "trade_date": trade_date,
                    "component": component,
                    "raw_value": json.dumps(raw_value, ensure_ascii=False, sort_keys=True),
                    "threshold": "; ".join(thresholds.get(key, key) for key in component_hits) or thresholds.get(component, ""),
                    "threshold_hit": any(bool(value) for value in component_hits.values()),
                    "score": component_scores.get(component, ""),
                    "source_field": _bcd_source_for_component(component, source_fields),
                    "missing_reason": "; ".join(item for item in sorted(missing) if item == component or item.startswith(component) or _missing_belongs_to_component(item, component)),
                }
            )
    independence_path = _write_bcd_independence_audit_markdown(payload, trace)
    return {"bcd_audit_trace_json": json_path, "bcd_audit_trace_csv": csv_path, "bcd_independence_audit_md": independence_path}



def _write_bcd_independence_audit_markdown(payload: Mapping[str, Any], trace: Mapping[str, Any]) -> Path:
    destination = Path("reports/audit")
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "bcd_independence_audit.md"
    source_fields = _mapping(trace.get("source_fields"))
    missing = [str(item) for item in trace.get("missing_components", []) or []]
    dependencies = [str(item) for item in trace.get("bcd_source_dependencies", []) or trace.get("source_dependencies", []) or []]
    tail_risk = payload.get("tail_risk")
    bcd = payload.get("bcd")
    comparison = "not comparable (BCD incomplete/null)" if bcd is None or tail_risk is None else f"abs(bcd - tail_risk) = {abs(float(bcd) - float(tail_risk)):.6f}"
    lines = [
        "# BCD Independence Audit",
        "",
        f"Trade date: {payload.get('trade_date')}",
        f"Calculation version: {trace.get('bcd_calculation_version', 'BCD-INDEPENDENT-V1')}",
        f"BCD Status: {trace.get('bcd_status') or trace.get('data_quality_status')}",
        f"Completeness score: {trace.get('bcd_data_completeness')}",
        f"Missing Inputs: {json.dumps(missing, ensure_ascii=False)}",
        "",
        "## Input sources",
        *[f"- {key}: {value}" for key, value in sorted(source_fields.items())],
        "",
        "## Calculation path",
        "- `src/tdt_rm/daily_runner.py::build_daily_payload_from_snapshot` calls `_bcd_result_from_snapshot` and writes BCD payload/audit fields.",
        "- `src/tdt_rm/daily_runner.py::_bcd_result_from_snapshot` maps independent snapshot breadth, leadership, sector, OTC/small-mid, and turnover fields into `BCDInput`.",
        "- `src/tdt_rm/bcd.py::score_bcd` validates completeness and returns `final_score=None` unless all required independent inputs are present.",
        "",
        "## Dependency graph",
        "```",
        "breadth_history ─┐",
        "main7_returns ──┤",
        "main7_weights ──┤",
        "sector_diffusion ├─> BCDInput -> score_bcd -> bcd",
        "otc_return_pct ─┤",
        "small_mid_breadth ─┤",
        "turnover_concentration_topn ─┘",
        "tail_risk ─X (forbidden dependency)",
        "options_csv.bcd ─X (forbidden dependency)",
        "```",
        "",
        "## Source dependencies",
        *[f"- {item}" for item in dependencies],
        "",
        "## Comparison against tail_risk",
        f"- Tail Risk: {tail_risk}",
        f"- BCD: {bcd}",
        f"- {comparison}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _bcd_explanation_lines(payload: Mapping[str, Any]) -> list[str]:
    trace = _mapping(_mapping(payload.get("traces")).get("bcd"))
    component_scores = _mapping(trace.get("component_scores"))
    missing = [str(item) for item in trace.get("missing_components", []) or []]
    if not trace:
        return ["資料限制：", "１、缺少 BCD trace；此分數不得視為完整拉積盤判斷。"]
    if missing:
        priority = ("sector_breadth", "turnover_concentration_topn", "main7_returns", "main7_weights", "breadth_history")
        ordered_missing = [item for item in priority if item in missing]
        ordered_missing.extend(item for item in missing if item not in ordered_missing and not item.endswith("_concentration") and not item.endswith("_weakness") and not item.endswith("_diffusion"))
        shown = ordered_missing[:3]
        return [
            "資料限制：",
            *[f"{_FULLWIDTH_NUMBERS.get(index, str(index))}、缺少 {_bcd_missing_label(item)}" for index, item in enumerate(shown, start=1)],
            f"{_FULLWIDTH_NUMBERS.get(len(shown) + 1, str(len(shown) + 1))}、BCD 狀態為 INCOMPLETE，分數為 null，不得視為完整拉積盤判斷",
        ]
    ranked = sorted(component_scores.items(), key=lambda item: float(item[1]), reverse=True)
    if not ranked:
        return ["主要原因：", "１、未觸發明顯市場集中度或拉積盤條件。"]
    return ["主要原因：", *[f"{_FULLWIDTH_NUMBERS.get(index, str(index))}、{_bcd_component_label(name)}：{_format_value(score)}" for index, (name, score) in enumerate(ranked[:3], start=1)]]


def _bcd_missing_label(name: str) -> str:
    return {
        "sector_breadth": "sector breadth",
        "turnover_concentration_topn": "Top-N turnover concentration",
        "main7_returns": "Main-7 returns",
        "main7_weights": "Main-7 weights",
        "breadth_history": "breadth history",
        "otc_return_pct": "OTC return",
        "small_mid_breadth": "small/mid breadth",
    }.get(name, name)


def _bcd_component_label(name: str) -> str:
    return {
        "index_breadth_divergence": "加權與市場廣度背離",
        "main7_concentration": "Main-7 權值集中",
        "sector_diffusion": "產業擴散不足",
        "small_mid_weakness": "OTC／中小型股弱勢",
        "turnover_concentration": "Top-N 成交集中且參與不足",
    }.get(name, name)


def _breadth_history_from_row(row: Mapping[str, Any]) -> tuple[BreadthBar, ...]:
    raw = row.get("breadth_history") or row.get("advancing_declining_history")
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return ()
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return ()
    bars: list[BreadthBar] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        adv = item.get("advancing_issues") or item.get("advancers")
        dec = item.get("declining_issues") or item.get("decliners")
        if adv in {None, ""} or dec in {None, ""}:
            continue
        bars.append(BreadthBar(advancing_issues=int(float(adv)), declining_issues=int(float(dec)), taiex_return_pct=_optional_number(item.get("taiex_return_pct")), trade_date=str(item.get("trade_date") or item.get("date") or "") or None))
    return tuple(bars)


def _small_mid_breadth_from_row(row: Mapping[str, Any]) -> BreadthBar | None:
    adv = row.get("small_mid_advancing_issues")
    dec = row.get("small_mid_declining_issues")
    if adv in {None, ""} or dec in {None, ""}:
        return None
    return BreadthBar(advancing_issues=int(float(adv)), declining_issues=int(float(dec)), taiex_return_pct=_optional_number(row.get("small_mid_return_pct")), trade_date=str(row.get("observed_at") or row.get("trade_date") or "") or None)


def _mapping_of_float(value: Any) -> dict[str, float]:
    if isinstance(value, str) and value.strip():
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    if not isinstance(value, Mapping):
        return {}
    out: dict[str, float] = {}
    for key, item in value.items():
        parsed = _optional_number(item)
        if parsed is not None:
            out[str(key)] = parsed
    return out


def _mapping_of_bool(value: Any) -> dict[str, bool]:
    if isinstance(value, str) and value.strip():
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item).strip().lower() in {"true", "1", "yes", "y"} if isinstance(item, str) else bool(item) for key, item in value.items()}


def _int_or_zero(value: Any) -> int:
    parsed = _optional_number(value)
    return 0 if parsed is None else int(parsed)


def _bcd_threshold_descriptions() -> dict[str, str]:
    return {
        "index_breadth_divergence": "TAIEX up with weak advancing/declining breadth or breadth below history",
        "main7_concentration": "Main-7 outperformance with weak broad participation",
        "sector_diffusion": "Majority of sectors weak or below MA20",
        "small_mid_weakness": "OTC/small-mid participation weaker than TAIEX",
        "turnover_concentration": "Top-N turnover share high while broad participation weak",
    }


def _bcd_component_raw_value(component: str, raw_inputs: Mapping[str, Any]) -> Any:
    keys = {
        "index_breadth_divergence": ("taiex_return_pct", "advancing_issues", "declining_issues", "breadth_history"),
        "main7_concentration": ("taiex_return_pct", "advancing_issues", "declining_issues", "main7_returns", "main7_weights"),
        "sector_diffusion": ("sector_returns", "sector_above_ma20"),
        "small_mid_weakness": ("otc_return_pct", "small_mid_breadth"),
        "turnover_concentration": ("turnover_concentration_topn", "advancing_issues", "declining_issues"),
    }.get(component, ())
    return {key: raw_inputs.get(key) for key in keys}


def _bcd_source_for_component(component: str, source_fields: Mapping[str, Any]) -> str:
    keys = _bcd_component_raw_value(component, source_fields)
    return "; ".join(f"{key}={value}" for key, value in keys.items() if value)


def _missing_belongs_to_component(missing: str, component: str) -> bool:
    membership = {
        "index_breadth_divergence": {"breadth_history", "advancing_declining_issues"},
        "main7_concentration": {"main7_returns", "main7_weights", "advancing_declining_issues"},
        "sector_diffusion": {"sector_breadth", "sector_returns", "sector_above_ma20"},
        "small_mid_weakness": {"otc_return_pct", "small_mid_breadth"},
        "turnover_concentration": {"turnover_concentration_topn", "advancing_declining_issues"},
    }
    return missing in membership.get(component, set())


def _month_starts_desc(as_of: date, count: int) -> Iterable[date]:
    year = as_of.year
    month = as_of.month
    for _ in range(count):
        yield date(year, month, 1)
        month -= 1
        if month == 0:
            year -= 1
            month = 12


def _field_value(values: Sequence[Any], fields: Sequence[str], name: str, fallback_index: int) -> Any:
    if fields and name in fields:
        index = fields.index(name)
        if index < len(values):
            return values[index]
    return values[fallback_index]


def _parse_twse_date(value: Any) -> date:
    text = str(value).strip()
    parts = text.replace("/", "-").split("-")
    if len(parts) == 3 and len(parts[0]) <= 3:
        return date(int(parts[0]) + 1911, int(parts[1]), int(parts[2]))
    return date.fromisoformat(text.replace("/", "-"))


def _parse_number(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text in {"", "--", "-"}:
        raise ValueError(f"cannot parse numeric TWSE value: {value!r}")
    number = float(text)
    if not math.isfinite(number):
        raise ValueError(f"non-finite TWSE numeric value: {value!r}")
    return number


def _optional_number(value: Any) -> float | None:
    try:
        return _parse_number(value)
    except (TypeError, ValueError):
        return None


def _coerce_date(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _moving_average(values: Sequence[float], window: int) -> float:
    if len(values) < window:
        raise ValueError(f"at least {window} values are required")
    return sum(values[-window:]) / window


def _pct_change(previous: float, current: float) -> float:
    if previous == 0:
        return 0.0
    return (current - previous) / previous * 100.0


def _consecutive_down_days(closes: Sequence[float]) -> int:
    count = 0
    for index in range(len(closes) - 1, 0, -1):
        if closes[index] < closes[index - 1]:
            count += 1
        else:
            break
    return count


def _consecutive_below_ma20(closes: Sequence[float]) -> int:
    count = 0
    for end in range(len(closes), 19, -1):
        ma20 = _moving_average(closes[:end], 20)
        if closes[end - 1] < ma20:
            count += 1
        else:
            break
    return count


def _iso_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _detect_git_sha() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    sha = completed.stdout.strip()
    return sha or None
