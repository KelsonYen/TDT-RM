#!/usr/bin/env python3
"""TDT-RM V5.1.3 Rev.3 executable decision and drawdown/backtest tool.

The tool turns the frozen specification into a small command-line program:

* ``evaluate`` reads model inputs and emits daily regime, signal, exposure cap,
  crash probability, and BCD state.
* ``backtest`` applies those exposure caps to a price series and reports the
  resulting equity curve, cumulative return, maximum drawdown, and signal stats.

CSV column names are intentionally close to the specification so the model can be
run from a spreadsheet export without a database dependency.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

MODEL_NAME = "TDT-RM V5.1.3 Decision Matrix Patch Rev.3 Final Freeze"

EXPOSURE_BY_SIGNAL = {
    "綠燈": "80–100%",
    "黃燈": "60–80%",
    "黃燈強化": "50–70%",
    "橘燈": "40–50%",
    "紅燈": "20–30%以下",
}

# The backtest uses the conservative top of each allowed exposure range as the
# strategy's maximum stock allocation. Users can override these values in code if
# they prefer the low end of each range.
DEFAULT_EXPOSURE_WEIGHTS = {
    "綠燈": 1.00,
    "黃燈": 0.80,
    "黃燈強化": 0.70,
    "橘燈": 0.50,
    "紅燈": 0.30,
}


@dataclass(frozen=True)
class ModelInput:
    """Minimum fields required to execute the decision matrix."""

    date: str
    tcwrs: float
    mhs: float
    eti5_total: int
    tail_risk: float
    bcd: float
    taiex: float | None = None
    ma20: float | None = None
    ma60: float | None = None
    consecutive_down_days: int = 0
    taiex_not_below_ma60_for_2_days: bool = False
    taiex_rebounds_from_below_ma60: bool = False
    taiex_back_above_ma60: bool = False
    close: float | None = None


@dataclass(frozen=True)
class ModelOutput:
    date: str
    model: str
    regime_state: str
    signal: str
    equity_exposure_limit: str
    crash_probability: float
    bcd_state: str
    bcd_for_signal: float
    bcd_can_upgrade_signal: bool


@dataclass(frozen=True)
class BacktestRow:
    date: str
    close: float
    signal: str
    exposure: float
    index_return: float
    strategy_return: float
    equity: float
    drawdown: float


@dataclass(frozen=True)
class BacktestSummary:
    rows: list[BacktestRow]
    start_date: str
    end_date: str
    total_return: float
    buy_and_hold_return: float
    max_drawdown: float
    worst_drawdown_date: str
    signal_counts: dict[str, int]


def _to_float(row: dict[str, str], key: str, default: float | None = None) -> float | None:
    value = row.get(key, "")
    if value is None or value == "":
        return default
    return float(value)


def _to_int(row: dict[str, str], key: str, default: int = 0) -> int:
    value = row.get(key, "")
    if value is None or value == "":
        return default
    return int(float(value))


def _to_bool(row: dict[str, str], key: str, default: bool = False) -> bool:
    value = row.get(key, "")
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "是"}


def read_inputs(path: Path) -> list[ModelInput]:
    """Read model inputs from CSV."""

    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        required = {"date", "tcwrs", "mhs", "eti5_total", "tail_risk", "bcd"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"missing required CSV columns: {', '.join(sorted(missing))}")

        inputs: list[ModelInput] = []
        for row in reader:
            taiex = _to_float(row, "taiex", _to_float(row, "close"))
            inputs.append(
                ModelInput(
                    date=row["date"],
                    tcwrs=float(row["tcwrs"]),
                    mhs=float(row["mhs"]),
                    eti5_total=_to_int(row, "eti5_total"),
                    tail_risk=float(row["tail_risk"]),
                    bcd=float(row["bcd"]),
                    taiex=taiex,
                    ma20=_to_float(row, "ma20"),
                    ma60=_to_float(row, "ma60"),
                    consecutive_down_days=_to_int(row, "consecutive_down_days"),
                    taiex_not_below_ma60_for_2_days=_to_bool(row, "taiex_not_below_ma60_for_2_days"),
                    taiex_rebounds_from_below_ma60=_to_bool(row, "taiex_rebounds_from_below_ma60"),
                    taiex_back_above_ma60=_to_bool(row, "taiex_back_above_ma60"),
                    close=_to_float(row, "close", taiex),
                )
            )
    return inputs


def crash_probability(item: ModelInput, bcd_for_signal: float | None = None) -> float:
    """Calculate auxiliary crash probability; it never upgrades to red by itself."""

    bcd_value = item.bcd if bcd_for_signal is None else bcd_for_signal
    raw = item.tcwrs * 0.40 + (item.eti5_total * 20) * 0.30 + item.tail_risk * 0.20 + bcd_value * 0.10
    return round(min(raw, 100.0), 2)


def determine_bcd_state(item: ModelInput) -> tuple[str, float, bool]:
    """Apply BCD state-machine priority and return state, score used for upgrades, and upgrade permission."""

    taiex = item.taiex
    below_ma20 = taiex is not None and item.ma20 is not None and taiex < item.ma20
    below_ma60 = taiex is not None and item.ma60 is not None and taiex < item.ma60
    above_ma20 = taiex is not None and item.ma20 is not None and taiex > item.ma20
    above_ma60 = taiex is not None and item.ma60 is not None and taiex > item.ma60

    if item.consecutive_down_days > 3:
        return "upgrade_suspended", item.bcd, False
    if below_ma60:
        return "upgrade_suspended", item.bcd, False
    if below_ma20 or (item.taiex_rebounds_from_below_ma60 and not item.taiex_back_above_ma60):
        return "restricted", min(item.bcd, 50.0), False
    if above_ma60 and item.taiex_not_below_ma60_for_2_days:
        return "full_recovery", item.bcd, True
    if above_ma20 and item.consecutive_down_days <= 3:
        return "normal", item.bcd, True
    return "unknown", item.bcd, False


def determine_regime(item: ModelInput) -> str:
    """Determine regime in the fixed Crash -> Fragile -> Hot -> Calm order."""

    if item.tcwrs >= 76 or item.eti5_total >= 4 or (item.tcwrs >= 61 and item.eti5_total >= 3):
        return "Crash"
    if item.tcwrs >= 41 or item.eti5_total >= 2 or item.tail_risk >= 61:
        return "Fragile"
    if item.mhs >= 71 and item.tcwrs <= 40 and item.eti5_total <= 1:
        return "Hot"
    if item.tcwrs <= 20 and item.eti5_total == 0 and item.tail_risk <= 40 and item.mhs <= 70:
        return "Calm"
    return "Neutral"


def determine_signal(item: ModelInput, bcd_for_signal: float, bcd_can_upgrade_signal: bool) -> str:
    """Determine five-light signal in the fixed red-to-green order."""

    bcd_upgrade_valid = bcd_can_upgrade_signal and item.taiex is not None and item.ma20 is not None and item.taiex > item.ma20

    if item.tcwrs >= 76:
        return "紅燈"
    if item.eti5_total >= 4:
        return "紅燈"
    if item.tcwrs >= 61 and item.eti5_total >= 3:
        return "紅燈"

    if 61 <= item.tcwrs <= 75 and item.eti5_total >= 2:
        return "橘燈"
    if item.eti5_total >= 3 and item.tcwrs >= 41:
        return "橘燈"
    if item.tcwrs >= 41 and item.tail_risk >= 61 and item.eti5_total >= 2:
        return "橘燈"
    if bcd_upgrade_valid and bcd_for_signal >= 61 and item.tcwrs >= 41 and item.eti5_total >= 2:
        return "橘燈"

    if 41 <= item.tcwrs <= 60:
        return "黃燈強化"
    if item.mhs >= 86 and item.tcwrs >= 30:
        return "黃燈強化"
    if item.eti5_total >= 2 and item.tcwrs >= 21:
        return "黃燈強化"
    if item.tail_risk >= 61 and item.tcwrs >= 21:
        return "黃燈強化"
    if bcd_upgrade_valid and bcd_for_signal >= 61 and item.tcwrs >= 21:
        return "黃燈強化"

    if 21 <= item.tcwrs <= 40:
        return "黃燈"
    if item.mhs >= 71:
        return "黃燈"
    if item.eti5_total >= 1:
        return "黃燈"
    if item.tail_risk >= 41:
        return "黃燈"
    if bcd_for_signal >= 41:
        return "黃燈"

    if item.tcwrs <= 20 and item.eti5_total == 0 and item.tail_risk <= 40 and bcd_for_signal <= 40 and item.mhs <= 70:
        return "綠燈"
    return "黃燈"


def evaluate(item: ModelInput) -> ModelOutput:
    bcd_state, bcd_for_signal, bcd_can_upgrade_signal = determine_bcd_state(item)
    signal = determine_signal(item, bcd_for_signal, bcd_can_upgrade_signal)
    return ModelOutput(
        date=item.date,
        model=MODEL_NAME,
        regime_state=determine_regime(item),
        signal=signal,
        equity_exposure_limit=EXPOSURE_BY_SIGNAL[signal],
        crash_probability=crash_probability(item, bcd_for_signal),
        bcd_state=bcd_state,
        bcd_for_signal=round(bcd_for_signal, 2),
        bcd_can_upgrade_signal=bcd_can_upgrade_signal,
    )


def backtest(inputs: list[ModelInput], initial_equity: float = 1.0) -> BacktestSummary:
    """Backtest daily exposure caps and calculate maximum drawdown."""

    if len(inputs) < 2:
        raise ValueError("backtest requires at least two rows")
    if any(item.close is None or not math.isfinite(item.close) for item in inputs):
        raise ValueError("backtest requires a finite close column on every row")

    rows: list[BacktestRow] = []
    equity = initial_equity
    peak = initial_equity
    max_drawdown = 0.0
    worst_drawdown_date = inputs[0].date
    signal_counts: dict[str, int] = {}

    first_output = evaluate(inputs[0])
    signal_counts[first_output.signal] = 1
    rows.append(
        BacktestRow(
            date=inputs[0].date,
            close=float(inputs[0].close),
            signal=first_output.signal,
            exposure=DEFAULT_EXPOSURE_WEIGHTS[first_output.signal],
            index_return=0.0,
            strategy_return=0.0,
            equity=equity,
            drawdown=0.0,
        )
    )

    for previous, current in zip(inputs, inputs[1:]):
        previous_signal = evaluate(previous).signal
        current_signal = evaluate(current).signal
        signal_counts[current_signal] = signal_counts.get(current_signal, 0) + 1

        exposure = DEFAULT_EXPOSURE_WEIGHTS[previous_signal]
        index_return = float(current.close) / float(previous.close) - 1.0
        strategy_return = exposure * index_return
        equity *= 1.0 + strategy_return
        peak = max(peak, equity)
        drawdown = equity / peak - 1.0
        if drawdown < max_drawdown:
            max_drawdown = drawdown
            worst_drawdown_date = current.date
        rows.append(
            BacktestRow(
                date=current.date,
                close=float(current.close),
                signal=current_signal,
                exposure=DEFAULT_EXPOSURE_WEIGHTS[current_signal],
                index_return=round(index_return, 6),
                strategy_return=round(strategy_return, 6),
                equity=round(equity, 6),
                drawdown=round(drawdown, 6),
            )
        )

    buy_and_hold_return = float(inputs[-1].close) / float(inputs[0].close) - 1.0
    return BacktestSummary(
        rows=rows,
        start_date=inputs[0].date,
        end_date=inputs[-1].date,
        total_return=round(equity / initial_equity - 1.0, 6),
        buy_and_hold_return=round(buy_and_hold_return, 6),
        max_drawdown=round(max_drawdown, 6),
        worst_drawdown_date=worst_drawdown_date,
        signal_counts=signal_counts,
    )


def _write_csv(rows: Iterable[dict[str, Any]], output: Path | None) -> None:
    rows = list(rows)
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    fp = output.open("w", encoding="utf-8", newline="") if output else sys.stdout
    try:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if output:
            fp.close()


def command_evaluate(args: argparse.Namespace) -> None:
    outputs = [asdict(evaluate(item)) for item in read_inputs(args.input)]
    if args.format == "json":
        text = json.dumps(outputs, ensure_ascii=False, indent=2)
        if args.output:
            args.output.write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
    else:
        _write_csv(outputs, args.output)


def command_backtest(args: argparse.Namespace) -> None:
    summary = backtest(read_inputs(args.input), initial_equity=args.initial_equity)
    if args.output:
        _write_csv([asdict(row) for row in summary.rows], args.output)
    payload = asdict(summary)
    payload.pop("rows")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run TDT-RM V5.1.3 Rev.3 and calculate strategy drawdown.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    evaluate_parser = subparsers.add_parser("evaluate", help="evaluate model signal rows")
    evaluate_parser.add_argument("input", type=Path, help="input CSV path")
    evaluate_parser.add_argument("--format", choices=("csv", "json"), default="csv")
    evaluate_parser.add_argument("--output", type=Path, help="optional output file")
    evaluate_parser.set_defaults(func=command_evaluate)

    backtest_parser = subparsers.add_parser("backtest", help="apply signal exposure caps and compute drawdown")
    backtest_parser.add_argument("input", type=Path, help="input CSV path with close prices")
    backtest_parser.add_argument("--initial-equity", type=float, default=1.0)
    backtest_parser.add_argument("--output", type=Path, help="optional equity-curve CSV path")
    backtest_parser.set_defaults(func=command_backtest)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except Exception as exc:  # CLI boundary: keep errors readable for spreadsheet users.
        parser.exit(1, f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
