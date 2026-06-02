"""Run the TDT-RM V5.1.4 2022 TAIEX bear-market daily backtest.

The repository does not ship licensed institutional breadth/foreign-flow feeds,
so this reproducible script uses an embedded public TAIEX daily close tape and
only the permitted ETI-1 price proxy while marking unavailable ETI inputs unavailable.  The five-light
signal itself is the V5.1.4 Backtest Calibration Patch decision matrix.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tdt_rm import (
    CrashProbabilityInput,
    BearTrendInput,
    DecisionMatrixInput,
    ETI5Input,
    TCWRSInput,
    score_bear_trend_filter,
    score_crash_probability,
    score_eti5,
    score_tcwrs,
    resolve_five_light_signal,
)

# Source: countryeconomy.com monthly TAIEX historical pages for 2021-12 and 2022-01..2022-12.
TAIEX_CLOSE_TEXT = """
2021-12-01,17585.99
2021-12-02,17724.88
2021-12-03,17697.14
2021-12-06,17688.21
2021-12-07,17796.92
2021-12-08,17832.42
2021-12-09,17914.12
2021-12-10,17826.26
2021-12-13,17767.60
2021-12-14,17599.37
2021-12-15,17660.10
2021-12-16,17785.74
2021-12-17,17812.59
2021-12-20,17669.11
2021-12-21,17789.27
2021-12-22,17826.83
2021-12-23,17946.66
2021-12-24,17961.64
2021-12-27,18048.94
2021-12-28,18196.81
2021-12-29,18248.28
2021-12-30,18218.84
2022-01-03,18270.51
2022-01-04,18526.35
2022-01-05,18499.96
2022-01-06,18367.92
2022-01-07,18169.76
2022-01-10,18239.38
2022-01-11,18288.21
2022-01-12,18375.40
2022-01-13,18436.93
2022-01-14,18403.33
2022-01-17,18525.44
2022-01-18,18378.64
2022-01-19,18227.46
2022-01-20,18218.28
2022-01-21,17899.30
2022-01-24,17989.04
2022-01-25,17701.12
2022-01-26,17674.40
2022-02-07,17900.30
2022-02-08,17966.56
2022-02-09,18151.76
2022-02-10,18338.05
2022-02-11,18310.94
2022-02-14,17997.67
2022-02-15,17951.81
2022-02-16,18231.47
2022-02-17,18268.57
2022-02-18,18232.35
2022-02-21,18221.49
2022-02-22,17969.29
2022-02-23,18055.73
2022-02-24,17594.55
2022-02-25,17652.18
2022-03-01,17898.25
2022-03-02,17867.60
2022-03-03,17934.40
2022-03-04,17736.52
2022-03-07,17178.69
2022-03-08,16825.25
2022-03-09,17015.36
2022-03-10,17433.20
2022-03-11,17264.74
2022-03-14,17263.04
2022-03-15,16926.06
2022-03-16,16940.83
2022-03-17,17448.22
2022-03-18,17456.52
2022-03-21,17560.36
2022-03-22,17559.71
2022-03-23,17731.37
2022-03-24,17699.06
2022-03-25,17676.95
2022-03-28,17520.01
2022-03-29,17548.66
2022-03-30,17740.56
2022-03-31,17693.47
2022-04-01,17625.59
2022-04-06,17522.50
2022-04-07,17178.63
2022-04-08,17284.54
2022-04-11,17048.37
2022-04-12,16990.91
2022-04-13,17301.65
2022-04-14,17245.65
2022-04-15,17004.18
2022-04-18,16898.87
2022-04-19,16993.40
2022-04-20,17148.88
2022-04-21,17127.95
2022-04-22,17025.09
2022-04-25,16620.90
2022-04-26,16644.79
2022-04-27,16303.35
2022-04-28,16419.38
2022-04-29,16592.18
2022-05-03,16498.90
2022-05-04,16565.83
2022-05-05,16696.12
2022-05-06,16408.20
2022-05-09,16048.92
2022-05-10,16061.70
2022-05-11,16006.25
2022-05-12,15616.68
2022-05-13,15832.54
2022-05-16,15901.04
2022-05-17,16056.09
2022-05-18,16296.86
2022-05-19,16020.32
2022-05-20,16144.85
2022-05-23,16156.41
2022-05-24,15963.63
2022-05-25,16104.03
2022-05-26,15968.83
2022-05-27,16266.22
2022-05-30,16610.62
2022-05-31,16807.77
2022-06-01,16675.09
2022-06-02,16552.57
2022-06-06,16605.96
2022-06-07,16512.88
2022-06-08,16670.51
2022-06-09,16621.34
2022-06-10,16460.12
2022-06-13,16070.98
2022-06-14,16047.37
2022-06-15,15999.25
2022-06-16,15838.61
2022-06-17,15641.26
2022-06-20,15367.58
2022-06-21,15728.64
2022-06-22,15347.75
2022-06-23,15176.44
2022-06-24,15303.32
2022-06-27,15548.01
2022-06-28,15439.92
2022-06-29,15240.13
2022-06-30,14825.73
2022-07-01,14343.08
2022-07-04,14217.06
2022-07-05,14349.20
2022-07-06,13985.51
2022-07-07,14336.27
2022-07-08,14464.53
2022-07-11,14340.53
2022-07-12,13950.62
2022-07-13,14324.68
2022-07-14,14438.52
2022-07-15,14550.62
2022-07-18,14719.64
2022-07-19,14694.08
2022-07-20,14733.22
2022-07-21,14937.70
2022-07-22,14949.36
2022-07-25,14936.33
2022-07-26,14806.78
2022-07-27,14921.59
2022-07-28,14891.90
2022-07-29,15000.07
2022-08-01,14981.69
2022-08-02,14747.23
2022-08-03,14777.02
2022-08-04,14702.20
2022-08-05,15036.04
2022-08-08,15020.41
2022-08-09,15050.28
2022-08-10,14939.02
2022-08-11,15197.85
2022-08-12,15288.97
2022-08-15,15417.35
2022-08-16,15420.57
2022-08-17,15465.45
2022-08-18,15396.76
2022-08-19,15408.78
2022-08-22,15245.14
2022-08-23,15095.89
2022-08-24,15069.19
2022-08-25,15200.04
2022-08-26,15278.44
2022-08-29,14926.19
2022-08-30,14953.63
2022-08-31,15095.44
2022-09-01,14801.86
2022-09-02,14673.04
2022-09-05,14661.10
2022-09-06,14677.20
2022-09-07,14410.05
2022-09-08,14583.42
2022-09-12,14807.43
2022-09-13,14894.41
2022-09-14,14658.31
2022-09-15,14670.04
2022-09-16,14561.76
2022-09-19,14425.68
2022-09-20,14549.30
2022-09-21,14424.52
2022-09-22,14284.63
2022-09-23,14118.38
2022-09-26,13778.19
2022-09-27,13826.59
2022-09-28,13466.07
2022-09-29,13534.26
2022-09-30,13424.58
2022-10-03,13300.48
2022-10-04,13576.52
2022-10-05,13801.43
2022-10-06,13892.05
2022-10-07,13702.28
2022-10-11,13106.03
2022-10-12,13081.24
2022-10-13,12810.73
2022-10-14,13128.12
2022-10-17,12966.05
2022-10-18,13124.68
2022-10-19,12976.76
2022-10-20,12946.10
2022-10-21,12819.20
2022-10-24,12856.98
2022-10-25,12666.12
2022-10-26,12729.05
2022-10-27,12926.37
2022-10-28,12788.42
2022-10-31,12949.75
2022-11-01,13037.21
2022-11-02,13100.17
2022-11-03,12986.60
2022-11-04,13026.71
2022-11-07,13223.73
2022-11-08,13347.76
2022-11-09,13638.81
2022-11-10,13503.76
2022-11-11,14007.56
2022-11-14,14174.90
2022-11-15,14546.31
2022-11-16,14537.35
2022-11-17,14535.23
2022-11-18,14504.99
2022-11-19,14504.99
2022-11-21,14449.39
2022-11-22,14542.20
2022-11-23,14608.54
2022-11-24,14784.00
2022-11-25,14778.51
2022-11-28,14556.87
2022-11-29,14709.64
2022-11-30,14879.55
2022-12-01,15012.80
2022-12-02,14970.68
2022-12-05,14980.74
2022-12-06,14728.88
2022-12-07,14630.01
2022-12-08,14553.04
2022-12-09,14705.43
2022-12-12,14612.59
2022-12-13,14522.96
2022-12-14,14739.36
2022-12-15,14734.13
2022-12-16,14528.55
2022-12-19,14433.32
2022-12-20,14170.03
2022-12-21,14234.40
2022-12-22,14442.94
2022-12-23,14271.63
2022-12-26,14285.13
2022-12-27,14328.43
2022-12-28,14173.10
2022-12-29,14085.02
2022-12-30,14137.69
"""


@dataclass(frozen=True)
class Bar:
    observed_at: date
    close: float


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="outputs/tdt_rm_v5_1_4_2022_bear_market_backtest.csv")
    parser.add_argument("--summary", default="outputs/tdt_rm_v5_1_4_2022_bear_market_summary.json")
    args = parser.parse_args()

    bars = _load_bars()
    rows = []
    peak = max(bar.close for bar in bars if bar.observed_at.year < 2022)
    for idx, bar in enumerate(bars):
        peak = max(peak, bar.close)
        if bar.observed_at.year != 2022:
            continue
        history = bars[: idx + 1]
        row = _score_day(history, peak)
        rows.append(row)

    _apply_stability_rules(rows)
    _annotate_outcomes(rows)
    summary = _summarize(rows)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    summary_path = Path(args.summary)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"csv": str(out), "summary": str(summary_path), **summary}, indent=2))


def _load_bars() -> list[Bar]:
    bars = []
    for line in TAIEX_CLOSE_TEXT.strip().splitlines():
        raw_date, raw_close = line.split(",")
        bars.append(Bar(datetime.strptime(raw_date, "%Y-%m-%d").date(), float(raw_close)))
    return bars


def _score_day(history: list[Bar], peak: float) -> dict[str, object]:
    closes = [bar.close for bar in history]
    close = closes[-1]
    prev_close = closes[-2] if len(closes) >= 2 else close
    ma5 = _ma(closes, 5)
    ma20 = _ma(closes, 20)
    ma60 = _ma(closes, 60)
    previous_ma20 = _ma(closes[:-1], 20)
    previous_ma60 = _ma(closes[:-1], 60)
    return_60d = _pct(closes[-61], close) if len(closes) >= 61 else 0.0
    one_day = _pct(prev_close, close)
    two_day = _pct(closes[-3], close) if len(closes) >= 3 else 0.0
    five_day = _pct(closes[-6], close) if len(closes) >= 6 else 0.0
    close_below_ma20_days = _consecutive(lambda value: value < ma20, closes)
    down_days = _consecutive_down(closes)
    drawdown = max(0.0, _pct(peak, close) * -1)
    twenty_returns = [_pct(closes[i - 1], closes[i]) for i in range(max(1, len(closes) - 19), len(closes))]
    volatility = statistics.pstdev(twenty_returns) if len(twenty_returns) > 1 else 0.0
    tail_risk = min(100.0, max(drawdown * 2.5, volatility * 18.0, abs(min(one_day, two_day)) * 9.0))
    bcd = min(100.0, max(drawdown * 2.0, max(0.0, (ma20 - close) / ma20 * 500.0), down_days * 12.0))

    tcwrs = score_tcwrs(
        TCWRSInput(
            close=close,
            ma5=ma5,
            ma20=ma20,
            ma60=ma60,
            ma20_slope=ma20 - previous_ma20,
            close_below_ma20_consecutive_days=close_below_ma20_days,
            one_day_return_pct=one_day,
            two_day_return_pct=two_day,
            close_is_black=one_day < -1.5,
            long_black_candle=one_day < -2.0,
            index_5d_return_pct=five_day,
            margin_balance_5d_decline_pct=max(0.0, -five_day / 2.0),
            index_down=one_day < 0,
            declining_issues_significantly_expand=one_day < -1.5,
            declining_issues_significantly_gt_advancing=one_day < -0.75,
            declining_gt_advancing_consecutive_days=down_days,
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
        CrashProbabilityInput(tcwrs=tcwrs.total_score, eti5_total=eti5.eti_score, tail_risk=tail_risk, bcd=bcd)
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
    signal = resolve_five_light_signal(
        DecisionMatrixInput(
            tcwrs=tcwrs.total_score,
            eti5_total=eti5.eti_score,
            tail_risk=tail_risk,
            bcd=bcd,
            cp_score=cp.cp_score,
            eti_available_count=eti5.eti_available_count,
            taiex=close,
            ma20=ma20,
            consecutive_down_days=down_days,
        ),
        bear_trend=bear_trend,
    )
    return {
        "Date": history[-1].observed_at.isoformat(),
        "TCWRS": tcwrs.total_score,
        "ETI-5": eti5.eti_score,
        "eti_available_count": eti5.eti_available_count,
        "eti_raw_score": eti5.eti_raw_score,
        "eti_capped_score": eti5.eti_capped_score,
        "eti_cap_reason": eti5.eti_cap_reason or "",
        "Tail Risk": round(tail_risk, 2),
        "BCD": round(bcd, 2),
        "CP": round(cp.cp_score, 2),
        "bear_trend_score": bear_trend.score,
        "bear_trend_floor_signal": bear_trend.floor_signal or "",
        "red_confirmed_by": signal.trace_output.get("red_confirmed_by") or "",
        "signal_before_stability_rule": signal.signal,
        "signal_after_stability_rule": signal.signal,
        "red_lock_active": False,
        "Signal": signal.signal,
        "Close": round(close, 2),
        "forward_5d_max_drawdown": "",
        "forward_10d_max_drawdown": "",
        "forward_20d_max_drawdown": "",
        "forward_40d_max_drawdown": "",
        "forward_60d_max_drawdown": "",
        "Forward 20D Max Drawdown %": "",
        "false_positive_20d": "",
        "false_positive_40d": "",
        "false_positive_60d": "",
        "delayed_valid_signal": "",
        "False Positive": "",
        "Drawdown Avoided %": "",
    }


def _apply_stability_rules(rows: list[dict[str, object]]) -> None:
    red_remaining = 0
    red_clear_days = 0
    previous_signal = "Green"
    for row in rows:
        base_signal = str(row["signal_before_stability_rule"])
        raw_red = base_signal == "Red"
        if raw_red:
            red_remaining = max(red_remaining, 3)
            red_clear_days = 0
        elif previous_signal == "Red":
            red_clear_days += 1
        else:
            red_clear_days = 0

        locked = False
        final_signal = base_signal
        if previous_signal == "Red":
            if red_remaining > 0 or red_clear_days < 2:
                final_signal = "Red"
                locked = not raw_red
            elif base_signal == "Green":
                final_signal = "Strengthened Yellow"
        if previous_signal == "Red" and final_signal == "Green":
            final_signal = "Strengthened Yellow"
        if final_signal == "Red":
            red_remaining = max(0, red_remaining - 1)
        row["signal_after_stability_rule"] = final_signal
        row["red_lock_active"] = locked
        row["Signal"] = final_signal
        previous_signal = final_signal


def _annotate_outcomes(rows: list[dict[str, object]]) -> None:
    closes = [float(row["Close"]) for row in rows]
    for idx, row in enumerate(rows):
        drawdowns = {window: _forward_max_drawdown(closes, idx, window) for window in (5, 10, 20, 40, 60)}
        risk = row["Signal"] in {"Red", "Orange"}
        row["forward_5d_max_drawdown"] = round(drawdowns[5], 2)
        row["forward_10d_max_drawdown"] = round(drawdowns[10], 2)
        row["forward_20d_max_drawdown"] = round(drawdowns[20], 2)
        row["forward_40d_max_drawdown"] = round(drawdowns[40], 2)
        row["forward_60d_max_drawdown"] = round(drawdowns[60], 2)
        row["Forward 20D Max Drawdown %"] = round(drawdowns[20], 2)
        row["false_positive_20d"] = bool(risk and drawdowns[20] > -5.0)
        row["false_positive_40d"] = bool(risk and drawdowns[40] > -8.0)
        row["false_positive_60d"] = bool(risk and drawdowns[60] > -10.0)
        row["delayed_valid_signal"] = bool(risk and drawdowns[20] > -5.0 and (drawdowns[40] <= -8.0 or drawdowns[60] <= -10.0))
        row["False Positive"] = bool(row["false_positive_20d"] and row["false_positive_40d"] and row["false_positive_60d"] and not row["delayed_valid_signal"])
        row["Drawdown Avoided %"] = round(abs(min(0.0, drawdowns[20], drawdowns[40], drawdowns[60])), 2) if risk else 0.0


def _forward_max_drawdown(closes: list[float], idx: int, window: int) -> float:
    future = closes[idx + 1 : idx + 1 + window]
    if not future:
        return 0.0
    return min(_pct(closes[idx], value) for value in future)


def _summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    red = sum(row["Signal"] == "Red" for row in rows)
    orange = sum(row["Signal"] == "Orange" for row in rows)
    false_positive = sum(row["False Positive"] is True for row in rows)
    max_avoided = max(float(row["Drawdown Avoided %"]) for row in rows)
    return {
        "model": "TDT-RM V5.1.4 Backtest Calibration Patch",
        "simulation": "daily",
        "period": "2022 bear market",
        "observations": len(rows),
        "red_signals": red,
        "orange_signals": orange,
        "false_positives": false_positive,
        "maximum_drawdown_avoided_pct": round(max_avoided, 2),
    }


def _ma(values: list[float], window: int) -> float:
    sample = values[-window:]
    return sum(sample) / len(sample)


def _pct(start: float, end: float) -> float:
    return (end - start) / start * 100 if start else 0.0


def _consecutive(predicate, values: list[float]) -> int:
    count = 0
    for value in reversed(values):
        if not predicate(value):
            break
        count += 1
    return count


def _consecutive_down(values: list[float]) -> int:
    count = 0
    for idx in range(len(values) - 1, 0, -1):
        if values[idx] >= values[idx - 1]:
            break
        count += 1
    return count


if __name__ == "__main__":
    main()
