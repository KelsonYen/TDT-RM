"""Run a TDT-RM V5.1.3 COVID-crash 2020 TAIEX stress test.

The repository does not ship licensed institutional breadth/foreign-flow feeds,
so this reproducible script uses embedded public TAIEX close observations and
conservative price-derived proxies for unavailable inputs.  The five-light
signal itself is the V5.1.3 Rev.3 Final Freeze decision matrix.
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
    DecisionMatrixInput,
    ETI5Input,
    TCWRSInput,
    resolve_five_light_signal,
    score_crash_probability,
    score_eti5,
    score_tcwrs,
)

# Sources: TWSE TAIEX Total Index historical pages for 2020-02,
# TWSE-sourced Land Bank market snapshots for 2020-03-18..2020-04-13,
# and public market-close reports for 2020-03-02..2020-03-17.
# The January 2020 peak seed is the 2020-01 high close referenced in TWSE monthly material.
JANUARY_2020_PEAK_CLOSE = 12179.81

TAIEX_CLOSE_TEXT = """
2020-02-03,11354.92
2020-02-04,11555.92
2020-02-05,11573.62
2020-02-06,11749.68
2020-02-07,11612.81
2020-02-10,11574.07
2020-02-11,11664.04
2020-02-12,11774.19
2020-02-13,11791.78
2020-02-14,11815.70
2020-02-17,11763.51
2020-02-18,11648.98
2020-02-19,11758.84
2020-02-20,11725.09
2020-02-21,11686.35
2020-02-24,11534.87
2020-02-25,11540.23
2020-02-26,11433.62
2020-02-27,11292.17
2020-03-02,11170.46
2020-03-03,11327.72
2020-03-04,11392.35
2020-03-05,11514.82
2020-03-06,11321.81
2020-03-09,10977.64
2020-03-10,11000.34
2020-03-11,10893.75
2020-03-12,10422.32
2020-03-13,10128.87
2020-03-16,9717.77
2020-03-17,9439.63
2020-03-18,9218.67
2020-03-19,8681.34
2020-03-20,9234.09
2020-03-23,8890.03
2020-03-24,9285.62
2020-03-25,9644.75
2020-03-26,9736.36
2020-03-27,9698.92
2020-03-30,9629.43
2020-03-31,9708.06
2020-04-01,9663.63
2020-04-06,9818.74
2020-04-07,9996.39
2020-04-08,10137.47
2020-04-09,10119.43
2020-04-10,10157.61
2020-04-13,10099.22
"""


@dataclass(frozen=True)
class Bar:
    observed_at: date
    close: float


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="outputs/tdt_rm_v5_1_3_2020_covid_crash_stress.csv")
    parser.add_argument("--summary", default="outputs/tdt_rm_v5_1_3_2020_covid_crash_summary.json")
    args = parser.parse_args()

    bars = _load_bars()
    rows = []
    peak = JANUARY_2020_PEAK_CLOSE
    for idx, bar in enumerate(bars):
        peak = max(peak, bar.close)
        history = bars[: idx + 1]
        rows.append(_score_day(history, peak))

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
            foreign_spot_net_sell_consecutive_days=down_days,
            usd_twd_3d_change_pct=max(0.0, -two_day / 2.0),
            index_down=one_day < 0,
            declining_issues_significantly_gt_advancing=one_day < -0.75,
            count_main_7_below_ma20=5 if close < ma20 else 0,
        )
    )
    cp = score_crash_probability(
        CrashProbabilityInput(tcwrs=tcwrs.total_score, eti5_total=eti5.eti_score, tail_risk=tail_risk, bcd=bcd)
    )
    signal = resolve_five_light_signal(
        DecisionMatrixInput(
            tcwrs=tcwrs.total_score,
            eti5_total=eti5.eti_score,
            tail_risk=tail_risk,
            bcd=bcd,
            taiex=close,
            ma20=ma20,
            consecutive_down_days=down_days,
        )
    )
    return {
        "Date": history[-1].observed_at.isoformat(),
        "TCWRS": tcwrs.total_score,
        "ETI-5": eti5.eti_score,
        "Tail Risk": round(tail_risk, 2),
        "BCD": round(bcd, 2),
        "CP": round(cp.cp_score, 2),
        "Signal": signal.signal,
        "Close": round(close, 2),
        "Forward 20D Max Drawdown %": "",
        "False Positive": "",
        "Drawdown Avoided %": "",
    }


def _annotate_outcomes(rows: list[dict[str, object]]) -> None:
    closes = [float(row["Close"]) for row in rows]
    for idx, row in enumerate(rows):
        future = closes[idx + 1 : idx + 21]
        if not future:
            max_dd = 0.0
        else:
            max_dd = min(_pct(closes[idx], value) for value in future)
        risk = row["Signal"] in {"Red", "Orange"}
        row["Forward 20D Max Drawdown %"] = round(max_dd, 2)
        row["False Positive"] = bool(risk and max_dd > -5.0)
        row["Drawdown Avoided %"] = round(abs(min(0.0, max_dd)), 2) if risk else 0.0


def _summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    red = sum(row["Signal"] == "Red" for row in rows)
    orange = sum(row["Signal"] == "Orange" for row in rows)
    false_positive = sum(row["False Positive"] is True for row in rows)
    max_avoided = max(float(row["Drawdown Avoided %"]) for row in rows)
    first_red = next((row["Date"] for row in rows if row["Signal"] == "Red"), None)
    first_orange = next((row["Date"] for row in rows if row["Signal"] == "Orange"), None)
    return {
        "model": "TDT-RM V5.1.3 Rev.3 Final Freeze",
        "simulation": "daily",
        "period": "2020 COVID crash",
        "observations": len(rows),
        "red_signals": red,
        "orange_signals": orange,
        "first_red_signal": first_red,
        "first_orange_signal": first_orange,
        "false_positives": false_positive,
        "maximum_drawdown_avoided_pct": round(max_avoided, 2),
    }


def _ma(values: list[float], window: int) -> float:
    if not values:
        return 0.0
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
