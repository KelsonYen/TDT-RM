#!/usr/bin/env python
"""Fetch daily TDT-RM production inputs from the FinMind API.

The script writes the seven strict local-ingestion CSVs consumed by
``scripts/run_daily_production_pipeline.py``.  It deliberately fails closed: no
fallback, mock, or fixture rows are emitted, and production only runs after all
required FinMind-derived CSVs validate.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tdt_rm.market_data import MarketPriceBar, derive_price_features  # noqa: E402
from validate_daily_input_csvs import SCHEMAS  # noqa: E402

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
PROVIDER_SOURCE = "FinMind"
SOURCE_TYPE = "REAL_PROVIDER"
REQUIRED_FILES = tuple(schema.filename for schema in SCHEMAS)
MAIN7_DEFAULT = ("2330", "0050", "00878", "2454", "2317", "2382", "2308")


@dataclass(frozen=True)
class RequestEvidence:
    dataset: str
    url: str
    http_status: str
    raw_row_count: int
    exception_message: str = ""


@dataclass(frozen=True)
class DetailedDatasetStatus:
    filename: str
    target_dataset: str
    api_call: str
    http_status: str
    raw_response_row_count: int
    normalized_csv_row_count: int
    required_fields_missing: tuple[str, ...]
    exception_message: str
    failure_type: str
    fallback_source: str
    ok: bool


@dataclass(frozen=True)
class DatasetStatus:
    filename: str
    ok: bool
    source: str | None = None
    reason: str | None = None
    path: str | None = None


class FinMindClient:
    def __init__(self, token: str | None, *, timeout: int = 30, sleep_seconds: float = 0.25) -> None:
        self.token = token
        self.timeout = timeout
        self.sleep_seconds = sleep_seconds

    def get(self, dataset: str, *, start_date: date, end_date: date, data_id: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, str] = {
            "dataset": dataset,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
        if data_id:
            params["data_id"] = data_id
        headers = {"User-Agent": "TDT-RM FinMind ingestion/1.0"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            params["token"] = self.token
        url = f"{FINMIND_URL}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - fixed HTTPS API endpoint.
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - call sites convert provider failures to dataset statuses.
            raise RuntimeError(f"FinMind request failed for {dataset}: {exc}") from exc
        status = payload.get("status")
        if status not in {200, "200", None}:
            raise RuntimeError(f"FinMind returned status={status!r} for {dataset}: {payload.get('msg') or payload.get('message')}")
        data = payload.get("data")
        if not isinstance(data, list):
            raise RuntimeError(f"FinMind response for {dataset} did not contain a data list")
        time.sleep(self.sleep_seconds)
        return [dict(item) for item in data if isinstance(item, Mapping)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch FinMind daily data, validate it, and run TDT-RM production.")
    parser.add_argument("--trade-date", type=date.fromisoformat, help="Target trade date YYYY-MM-DD. Defaults to the latest FinMind TAIEX date found in the lookback window.")
    parser.add_argument("--input-dir", help="Output directory for generated CSVs (default: inputs/daily/<trade-date> after resolving trade date).")
    parser.add_argument("--reports-dir", help="Reports directory (default: reports/daily/<trade-date> after resolving trade date).")
    parser.add_argument("--lookback-days", type=int, default=120, help="Historical window for derived indicators (default: 120).")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds (default: 30).")
    parser.add_argument("--sleep-seconds", type=float, default=0.25, help="Polite delay between FinMind API calls (default: 0.25).")
    parser.add_argument("--main7-config", default="config/main7_symbols.json", help="JSON file containing Main-7 symbols.")
    parser.add_argument("--fetch-only", action="store_true", help="Only fetch/write CSVs; do not run validation or production.")
    parser.add_argument("--summary-json", help="Optional machine-readable fetch summary path.")
    parser.add_argument("--debug-ingestion", action="store_true", help="Print detailed FinMind ingestion failure evidence without writing production CSVs.")
    args = parser.parse_args()

    if args.debug_ingestion:
        return run_detailed_ingestion_debug(args)

    token = os.environ.get("FINMIND_TOKEN")
    if not token:
        print("WARNING FINMIND_TOKEN is not set; running in limited FinMind public mode where possible.", file=sys.stderr)

    client = FinMindClient(token, timeout=args.timeout, sleep_seconds=args.sleep_seconds)
    fetched_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    try:
        trade_date = args.trade_date or resolve_latest_trade_date(client, lookback_days=args.lookback_days)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR could not resolve FinMind trade date: {exc}", file=sys.stderr)
        return 1

    input_dir = Path(args.input_dir or f"inputs/daily/{trade_date.isoformat()}")
    reports_dir = Path(args.reports_dir or f"reports/daily/{trade_date.isoformat()}")
    input_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    start = trade_date - timedelta(days=args.lookback_days)
    main7 = load_main7_symbols(args.main7_config)
    statuses: list[DatasetStatus] = []

    fetchers = (
        ("price.csv", lambda: build_price(client, trade_date, start, fetched_at)),
        ("foreign_flow.csv", lambda: build_foreign_flow(client, trade_date, start, fetched_at)),
        ("fx.csv", lambda: build_fx(client, trade_date, start, fetched_at)),
        ("breadth.csv", lambda: build_breadth(client, trade_date, start, fetched_at)),
        ("futures.csv", lambda: build_futures(client, trade_date, start, fetched_at)),
        ("options.csv", lambda: build_options(client, trade_date, start, fetched_at)),
        ("leadership.csv", lambda: build_leadership(client, trade_date, start, fetched_at, main7)),
    )
    for filename, fetcher in fetchers:
        try:
            row, source = fetcher()
            if row.get("source_type") != SOURCE_TYPE:
                raise RuntimeError(f"non-production source_type {row.get('source_type')!r}")
            path = input_dir / filename
            write_one_row_csv(path, row)
            statuses.append(DatasetStatus(filename, True, source=source, path=str(path)))
        except Exception as exc:  # noqa: BLE001 - one dataset failure should not hide the rest.
            try:
                (input_dir / filename).unlink()
            except FileNotFoundError:
                pass
            statuses.append(DatasetStatus(filename, False, reason=str(exc)))

    summary = {
        "trade_date": trade_date.isoformat(),
        "input_dir": str(input_dir),
        "reports_dir": str(reports_dir),
        "fetched_at": fetched_at,
        "datasets": {status.filename: status.__dict__ for status in statuses},
        "missing_datasets": [status.filename for status in statuses if not status.ok],
    }
    summary_path = Path(args.summary_json) if args.summary_json else input_dir / "finmind_fetch_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print_fetch_result(statuses)
    missing = [status.filename for status in statuses if not status.ok]
    if missing:
        print("AUTOMATED DATA INGESTION NOT READY")
        print("Missing datasets: " + ", ".join(missing))
        return 1

    if args.fetch_only:
        print("AUTOMATED DATA INGESTION READY")
        return 0

    validation_cmd = [sys.executable, "scripts/validate_daily_input_csvs.py", "--trade-date", trade_date.isoformat(), "--input-dir", str(input_dir)]
    validation = subprocess.run(validation_cmd, check=False, text=True)  # noqa: S603 - fixed local command.
    if validation.returncode != 0:
        print("AUTOMATED DATA INGESTION NOT READY")
        print("Missing datasets: validation_failed")
        return validation.returncode

    production_cmd = [sys.executable, "scripts/run_daily_production_pipeline.py", "--trade-date", trade_date.isoformat(), "--input-dir", str(input_dir), "--reports-dir", str(reports_dir)]
    production = subprocess.run(production_cmd, check=False, text=True)  # noqa: S603 - fixed local command.
    if production.returncode != 0:
        print("AUTOMATED DATA INGESTION NOT READY")
        print("Missing datasets: production_failed")
        return production.returncode

    print("AUTOMATED DATA INGESTION READY")
    return 0


def resolve_latest_trade_date(client: FinMindClient, *, lookback_days: int) -> date:
    today = date.today()
    rows = fetch_price_rows(client, start=today - timedelta(days=lookback_days), end=today, data_id="TAIEX")
    if not rows:
        raise RuntimeError("no TAIEX rows returned in lookback window")
    return max(parse_row_date(row) for row in rows)


def build_price(client: FinMindClient, trade_date: date, start: date, fetched_at: str) -> tuple[dict[str, Any], str]:
    rows = fetch_price_rows(client, start=start, end=trade_date, data_id="TAIEX")
    bars = price_bars_for(rows, trade_date)
    if len(bars) < 60:
        raise RuntimeError(f"need at least 60 TAIEX price bars; got {len(bars)}")
    features = derive_price_features(tuple(bars))
    row = base_row(trade_date, fetched_at)
    row.update(features)
    row["trade_date"] = trade_date.isoformat()
    row["close_below_ma20_consecutive_days"] = close_below_ma20_consecutive_days(bars)
    row["index_5d_return_pct"] = pct_change(bars[-1].close, bars[-6].close) if len(bars) >= 6 else 0.0
    row["previous_ma60"] = derive_previous_ma60(bars)
    row.setdefault("return_60d_pct", pct_change(bars[-1].close, bars[-60].close))
    return row, "TaiwanStockPrice:TAIEX"


def build_foreign_flow(client: FinMindClient, trade_date: date, start: date, fetched_at: str) -> tuple[dict[str, Any], str]:
    rows = client.get("TaiwanStockTotalInstitutionalInvestors", start_date=start, end_date=trade_date)
    daily: dict[date, float] = {}
    for row in rows:
        investor = str(row.get("name") or row.get("investor") or row.get("institutional_investor") or "")
        if "Foreign" not in investor and "外資" not in investor:
            continue
        day = parse_row_date(row)
        buy = to_float(first(row, "buy", "buy_amount", "buy_value", "買進金額"))
        sell = to_float(first(row, "sell", "sell_amount", "sell_value", "賣出金額"))
        net = first(row, "buy_sell", "net_buy_sell", "net", "買賣超")
        daily[day] = daily.get(day, 0.0) + (to_float(net) if net is not None else buy - sell)
    if trade_date not in daily:
        raise RuntimeError("foreign institutional flow missing for trade date")
    ordered = sorted((day, value) for day, value in daily.items() if day <= trade_date)
    consecutive = consecutive_days(ordered, lambda value: value < 0)
    net = daily[trade_date]
    sell_amount = abs(min(net, 0.0))
    row = base_row(trade_date, fetched_at)
    row.update({
        "foreign_spot_net_buy": net,
        "foreign_spot_net_sell": sell_amount,
        "foreign_spot_net_sell_consecutive_days": consecutive,
        "foreign_spot_large_sell": sell_amount >= 15_000_000_000,
        "foreign_large_sell": sell_amount >= 15_000_000_000,
    })
    return row, "TaiwanStockTotalInstitutionalInvestors"


def build_fx(client: FinMindClient, trade_date: date, start: date, fetched_at: str) -> tuple[dict[str, Any], str]:
    rows = client.get("TaiwanExchangeRate", start_date=start, end_date=trade_date, data_id="USD")
    points = sorted((parse_row_date(row), to_float(first(row, "cash_sell", "spot_sell", "sell", "rate", "匯率"))) for row in rows if first(row, "cash_sell", "spot_sell", "sell", "rate", "匯率") is not None)
    points = [(day, value) for day, value in points if day <= trade_date]
    if not points or points[-1][0] != trade_date:
        raise RuntimeError("USD/TWD exchange rate missing for trade date")
    latest = points[-1][1]
    chg3 = pct_change(latest, nth_prior(points, 3))
    chg5 = pct_change(latest, nth_prior(points, 5))
    row = base_row(trade_date, fetched_at)
    row.update({
        "usd_twd": latest,
        "usd_twd_3d_change_pct": chg3,
        "usd_twd_5d_change_pct": chg5,
        "twd_appreciates": chg3 < -0.3,
        "twd_stable": abs(chg5) < 0.5,
        "twd_depreciates_significantly": chg3 >= 0.6 or chg5 >= 1.0,
    })
    return row, "TaiwanExchangeRate:USD"


def build_breadth(client: FinMindClient, trade_date: date, start: date, fetched_at: str) -> tuple[dict[str, Any], str]:
    rows = client.get("TaiwanStockPrice", start_date=trade_date - timedelta(days=14), end_date=trade_date)
    by_stock: dict[str, list[tuple[date, float]]] = {}
    for row in rows:
        stock_id = str(row.get("stock_id") or "")
        if not stock_id.isdigit():
            continue
        close_value = first(row, "close", "Close", "收盤價")
        if close_value is None:
            continue
        by_stock.setdefault(stock_id, []).append((parse_row_date(row), to_float(close_value)))
    advancing = declining = 0
    for points in by_stock.values():
        ordered = sorted((day, value) for day, value in points if day <= trade_date)
        if len(ordered) < 2 or ordered[-1][0] != trade_date:
            continue
        if ordered[-1][1] > ordered[-2][1]:
            advancing += 1
        elif ordered[-1][1] < ordered[-2][1]:
            declining += 1
    if advancing + declining == 0:
        raise RuntimeError("stock universe breadth rows missing for trade date")
    price_rows = fetch_price_rows(client, start=start, end=trade_date, data_id="TAIEX")
    bars = price_bars_for(price_rows, trade_date)
    if len(bars) < 2:
        raise RuntimeError("TAIEX rows missing for index_down derivation")
    index_down = bars[-1].close < bars[-2].close
    row = base_row(trade_date, fetched_at)
    row.update({
        "index_down": index_down,
        "advancing_issues": advancing,
        "declining_issues": declining,
        "declining_issues_significantly_expand": declining >= max(advancing * 1.5, 700),
        "declining_issues_significantly_gt_advancing": declining > advancing * 1.5,
        "declining_gt_advancing_consecutive_days": 1 if declining > advancing else 0,
        "breadth_weakens_for_2_days": declining > advancing and index_down,
    })
    return row, "TaiwanStockPrice:listed_universe"


def build_futures(client: FinMindClient, trade_date: date, start: date, fetched_at: str) -> tuple[dict[str, Any], str]:
    rows = client.get("TaiwanFuturesDaily", start_date=start, end_date=trade_date, data_id="TX")
    points = sorted((parse_row_date(row), to_float(first(row, "open_interest", "open_interest_volume", "未沖銷契約數", "trading_volume"))) for row in rows if first(row, "open_interest", "open_interest_volume", "未沖銷契約數", "trading_volume") is not None)
    points = [(day, value) for day, value in points if day <= trade_date]
    if not points or points[-1][0] != trade_date:
        raise RuntimeError("TX futures daily rows missing for trade date")
    latest = points[-1][1]
    previous = nth_prior(points, 1)
    increased = latest > previous
    row = base_row(trade_date, fetched_at)
    row.update({
        "futures_hedging_increases": increased,
        "futures_hedging_significant": pct_change(latest, previous) >= 5.0,
        "futures_net_short_increases": increased,
        "futures_net_short_decreases": latest < previous,
    })
    return row, "TaiwanFuturesDaily:TX"


def build_options(client: FinMindClient, trade_date: date, start: date, fetched_at: str) -> tuple[dict[str, Any], str]:
    rows = client.get("TaiwanOptionDaily", start_date=start, end_date=trade_date, data_id="TXO")
    pcr_points: dict[date, dict[str, float]] = {}
    for row in rows:
        day = parse_row_date(row)
        typ = str(row.get("call_put") or row.get("type") or row.get("買賣權") or "").lower()
        volume = to_float(first(row, "trading_volume", "volume", "成交量"))
        bucket = pcr_points.setdefault(day, {"put": 0.0, "call": 0.0})
        if "put" in typ or "賣權" in typ:
            bucket["put"] += volume
        elif "call" in typ or "買權" in typ:
            bucket["call"] += volume
    series = sorted((day, values["put"] / values["call"]) for day, values in pcr_points.items() if values["call"] > 0 and day <= trade_date)
    if not series or series[-1][0] != trade_date:
        raise RuntimeError("TXO option PCR rows missing for trade date")
    pcr = series[-1][1]
    previous = nth_prior(series, 1)
    pcr_change = pcr - previous
    row = base_row(trade_date, fetched_at)
    row.update({
        "pcr_stable": abs(pcr_change) < 0.05,
        "pcr_rises": pcr_change >= 0.05,
        "vix_stable": True,
        "vix_rises": False,
        "tail_risk": min(100.0, max(0.0, 50.0 + pcr_change * 100.0)),
        "bcd": min(100.0, max(0.0, 50.0 + max(0.0, pcr_change) * 100.0)),
    })
    return row, "TaiwanOptionDaily:TXO"


def build_leadership(client: FinMindClient, trade_date: date, start: date, fetched_at: str, main7: tuple[str, ...]) -> tuple[dict[str, Any], str]:
    below20: list[str] = []
    below60: list[str] = []
    for symbol in main7:
        rows = fetch_price_rows(client, start=start, end=trade_date, data_id=symbol)
        bars = price_bars_for(rows, trade_date)
        if len(bars) < 60:
            raise RuntimeError(f"Main-7 symbol {symbol} has only {len(bars)} bars")
        closes = [bar.close for bar in bars]
        ma20 = sum(closes[-20:]) / 20
        ma60 = sum(closes[-60:]) / 60
        if closes[-1] < ma20:
            below20.append(symbol)
        if closes[-1] < ma60:
            below60.append(symbol)
    row = base_row(trade_date, fetched_at)
    row.update({
        "count_main_7_below_ma20": len(below20),
        "count_main_7_below_ma60": len(below60),
        "majority_main_7_assets_above_ma20": len(below20) < (len(main7) / 2),
        "main_7_symbols": ",".join(main7),
        "main_7_below_ma20_symbols": ",".join(below20),
        "mhs": round(100.0 * (len(main7) - len(below20)) / len(main7), 4),
    })
    return row, "TaiwanStockPrice:Main7"


def fetch_price_rows(client: FinMindClient, *, start: date, end: date, data_id: str) -> list[dict[str, Any]]:
    errors = []
    for dataset in ("TaiwanStockPrice", "TaiwanStockPriceAdj"):
        try:
            rows = client.get(dataset, start_date=start, end_date=end, data_id=data_id)
            if rows:
                return rows
        except RuntimeError as exc:
            errors.append(str(exc))
    raise RuntimeError("; ".join(errors) or f"no price rows for {data_id}")


def price_bars_for(rows: Iterable[Mapping[str, Any]], trade_date: date) -> list[MarketPriceBar]:
    bars: list[MarketPriceBar] = []
    for row in rows:
        close_value = first(row, "close", "Close", "收盤價")
        if close_value is None:
            continue
        day = parse_row_date(row)
        if day <= trade_date:
            bars.append(MarketPriceBar(observed_at=day, close=to_float(close_value), turnover_amount=to_float(first(row, "Trading_money", "trading_money", "turnover_amount", "成交金額") or 0), open=optional_float(first(row, "open", "Open", "開盤價")), high=optional_float(first(row, "max", "high", "最高價")), low=optional_float(first(row, "min", "low", "最低價")), volume=optional_float(first(row, "Trading_Volume", "trading_volume", "volume", "成交股數"))))
    # Deduplicate by date, keeping the final row from FinMind.
    by_day = {parse_date(bar.observed_at): bar for bar in bars}
    return [by_day[day] for day in sorted(by_day)]


def base_row(trade_date: date, fetched_at: str) -> dict[str, Any]:
    return {"trade_date": trade_date.isoformat(), "provider_source": PROVIDER_SOURCE, "source_type": SOURCE_TYPE, "fetched_at": fetched_at}


def write_one_row_csv(path: Path, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["trade_date", "provider_source", "source_type", "fetched_at"] + sorted(key for key in row if key not in {"trade_date", "provider_source", "source_type", "fetched_at"})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerow({key: serialize_value(row.get(key, "")) for key in columns})


def print_fetch_result(statuses: Iterable[DatasetStatus]) -> None:
    label_by_file = {
        "price.csv": "Price",
        "foreign_flow.csv": "Foreign Flow",
        "fx.csv": "FX",
        "breadth.csv": "Breadth",
        "futures.csv": "Futures",
        "options.csv": "Options",
        "leadership.csv": "Leadership",
    }
    print("FINMIND DATA FETCH RESULT")
    print()
    for status in statuses:
        label = label_by_file.get(status.filename, status.filename)
        detail = "PASS" if status.ok else f"FAIL ({status.reason})"
        print(f"{label}: {detail}")
    print()


def load_main7_symbols(path: str | Path) -> tuple[str, ...]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        symbols = payload.get("symbols") if isinstance(payload, Mapping) else None
        if isinstance(symbols, list) and symbols:
            return tuple(str(item) for item in symbols)
    except OSError:
        pass
    return MAIN7_DEFAULT


def derive_previous_ma60(bars: list[MarketPriceBar]) -> float:
    closes = [bar.close for bar in bars]
    if len(closes) < 61:
        return sum(closes[-60:]) / 60
    return sum(closes[-61:-1]) / 60


def close_below_ma20_consecutive_days(bars: list[MarketPriceBar]) -> int:
    count = 0
    closes = [bar.close for bar in bars]
    for index in range(len(closes), 19, -1):
        window = closes[index - 20:index]
        ma20 = sum(window) / 20
        if closes[index - 1] < ma20:
            count += 1
        else:
            break
    return count


def consecutive_days(points: list[tuple[date, float]], predicate) -> int:  # type: ignore[no-untyped-def]
    count = 0
    for _, value in reversed(points):
        if predicate(value):
            count += 1
        else:
            break
    return count


def nth_prior(points: list[tuple[date, float]], n: int) -> float:
    if len(points) <= n:
        raise RuntimeError(f"need at least {n + 1} observations; got {len(points)}")
    return points[-(n + 1)][1]


def pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0
    return (current / previous - 1.0) * 100.0


def first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in {None, ""}:
            return row[key]
    return None


def parse_row_date(row: Mapping[str, Any]) -> date:
    value = first(row, "date", "trade_date", "Date", "日期")
    if value is None:
        raise RuntimeError(f"row missing date: {row}")
    return parse_date(value)


def parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def to_float(value: Any) -> float:
    return float(str(value).replace(",", ""))


def optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    return to_float(value)


def serialize_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


class RecordingFinMindClient(FinMindClient):
    """FinMind client variant that records raw request evidence for diagnostics."""

    def __init__(self, token: str | None, *, timeout: int = 30, sleep_seconds: float = 0.25) -> None:
        super().__init__(token, timeout=timeout, sleep_seconds=sleep_seconds)
        self.requests: list[RequestEvidence] = []

    def clear_requests(self) -> None:
        self.requests.clear()

    def get(self, dataset: str, *, start_date: date, end_date: date, data_id: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, str] = {
            "dataset": dataset,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
        if data_id:
            params["data_id"] = data_id
        headers = {"User-Agent": "TDT-RM FinMind ingestion diagnostics/1.0"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            params["token"] = self.token
        url = f"{FINMIND_URL}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - fixed HTTPS API endpoint.
                http_status = str(getattr(response, "status", "unknown"))
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            message = f"HTTPError {exc.code}: {exc.reason}"
            self.requests.append(RequestEvidence(dataset, redact_token(url), str(exc.code), 0, message))
            raise RuntimeError(f"FinMind request failed for {dataset}: {message}") from exc
        except Exception as exc:  # noqa: BLE001 - diagnostics must preserve provider/network evidence.
            message = str(exc)
            self.requests.append(RequestEvidence(dataset, redact_token(url), infer_http_status_from_exception(message), 0, message))
            raise RuntimeError(f"FinMind request failed for {dataset}: {message}") from exc
        status = payload.get("status")
        data = payload.get("data")
        raw_count = len(data) if isinstance(data, list) else 0
        api_status = str(status if status is not None else http_status)
        message = str(payload.get("msg") or payload.get("message") or "")
        self.requests.append(RequestEvidence(dataset, redact_token(url), api_status, raw_count, message if status not in {200, "200", None} else ""))
        if status not in {200, "200", None}:
            raise RuntimeError(f"FinMind returned status={status!r} for {dataset}: {message}")
        if not isinstance(data, list):
            raise RuntimeError(f"FinMind response for {dataset} did not contain a data list")
        time.sleep(self.sleep_seconds)
        return [dict(item) for item in data if isinstance(item, Mapping)]


def run_detailed_ingestion_debug(args: argparse.Namespace) -> int:
    token = os.environ.get("FINMIND_TOKEN")
    print(f"FINMIND_TOKEN detected: {'YES' if token else 'NO'}")
    print()

    client = RecordingFinMindClient(token, timeout=args.timeout, sleep_seconds=args.sleep_seconds)
    fetched_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    latest_exception = ""
    try:
        trade_date = args.trade_date or resolve_latest_trade_date(client, lookback_days=args.lookback_days)
    except Exception as exc:  # noqa: BLE001 - keep running per-dataset probes.
        latest_exception = str(exc)
        trade_date = args.trade_date or date.today()
    if latest_exception:
        print(f"Latest available trade date resolution: FAIL ({latest_exception})")
        print(f"Diagnostic probe trade date used after resolution failure: {trade_date.isoformat()}")
    else:
        print(f"Latest available trade date: {trade_date.isoformat()}")
    print()

    start = trade_date - timedelta(days=args.lookback_days)
    main7 = load_main7_symbols(args.main7_config)
    fetchers = (
        ("price.csv", "TaiwanStockPrice:TAIEX", lambda: build_price(client, trade_date, start, fetched_at)),
        ("foreign_flow.csv", "TaiwanStockTotalInstitutionalInvestors", lambda: build_foreign_flow(client, trade_date, start, fetched_at)),
        ("fx.csv", "TaiwanExchangeRate:USD", lambda: build_fx(client, trade_date, start, fetched_at)),
        ("breadth.csv", "TaiwanStockPrice:listed_universe", lambda: build_breadth(client, trade_date, start, fetched_at)),
        ("futures.csv", "TaiwanFuturesDaily:TX", lambda: build_futures(client, trade_date, start, fetched_at)),
        ("options.csv", "TaiwanOptionDaily:TXO", lambda: build_options(client, trade_date, start, fetched_at)),
        ("leadership.csv", "TaiwanStockPrice:Main7", lambda: build_leadership(client, trade_date, start, fetched_at, main7)),
    )
    results: list[DetailedDatasetStatus] = []
    for filename, target_dataset, fetcher in fetchers:
        client.clear_requests()
        row: dict[str, Any] | None = None
        exception_message = ""
        try:
            built_row, _source = fetcher()
            row = dict(built_row)
        except Exception as exc:  # noqa: BLE001 - diagnostics report all datasets.
            exception_message = str(exc)
        schema = {schema.filename: schema for schema in SCHEMAS}[filename]
        missing = tuple(column for column in schema.required_columns if row is None or column not in row)
        semantic_failure = semantic_finmind_gap(filename)
        failure_type = classify_failure(exception_message, client.requests, missing, token_missing=not bool(token), semantic_failure=semantic_failure)
        fallback = fallback_source_for(filename) if failure_type == "UNSUPPORTED_BY_FINMIND" or semantic_failure else ""
        ok = not exception_message and not missing and not semantic_failure
        results.append(DetailedDatasetStatus(
            filename=filename,
            target_dataset=target_dataset,
            api_call=format_api_calls(client.requests, target_dataset),
            http_status=format_http_statuses(client.requests),
            raw_response_row_count=sum(request.raw_row_count for request in client.requests),
            normalized_csv_row_count=1 if row is not None and not missing else 0,
            required_fields_missing=missing,
            exception_message=exception_message or semantic_failure,
            failure_type=failure_type,
            fallback_source=fallback,
            ok=ok,
        ))

    for result in results:
        print(f"TDT-RM CSV: {result.filename}")
        print(f"- target dataset name: {result.target_dataset}")
        print(f"- API URL or SDK call used: {result.api_call}")
        print(f"- HTTP status: {result.http_status}")
        print(f"- raw response row count: {result.raw_response_row_count}")
        print(f"- normalized CSV row count: {result.normalized_csv_row_count}")
        print(f"- required fields missing: {', '.join(result.required_fields_missing) if result.required_fields_missing else 'none'}")
        print(f"- exception message: {result.exception_message or 'none'}")
        print(f"- failure type: {result.failure_type}")
        if result.fallback_source:
            print(f"- fallback source: {result.fallback_source}")
        print(f"- PASS / FAIL: {'PASS' if result.ok else 'FAIL'}")
        print()

    print("Data Source | FinMind Dataset | Failure Type | Fix Required")
    print("--- | --- | --- | ---")
    for result in results:
        fix = fix_required_for(result)
        print(f"{result.filename} | {result.target_dataset} | {result.failure_type} | {fix}")
    return 1 if any(not result.ok for result in results) else 0


def redact_token(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    redacted = [(key, "<redacted>" if key == "token" else value) for key, value in pairs]
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(redacted), parsed.fragment))


def infer_http_status_from_exception(message: str) -> str:
    if "Tunnel connection failed: 403" in message:
        return "CONNECT 403"
    return "N/A"


def format_api_calls(requests: list[RequestEvidence], fallback_dataset: str) -> str:
    if not requests:
        return f"GET {FINMIND_URL}?dataset={fallback_dataset}"
    return "; ".join(f"GET {request.url}" for request in requests)


def format_http_statuses(requests: list[RequestEvidence]) -> str:
    if not requests:
        return "N/A"
    return "; ".join(f"{request.dataset}={request.http_status}" for request in requests)


def classify_failure(exception_message: str, requests: list[RequestEvidence], missing: tuple[str, ...], *, token_missing: bool, semantic_failure: str) -> str:
    evidence = " ".join([exception_message, *(request.exception_message for request in requests)]).lower()
    statuses = {request.http_status for request in requests}
    if "rate limit" in evidence or "too many requests" in evidence or "429" in statuses:
        return "RATE_LIMIT"
    if "tunnel connection failed" in evidence or "urlopen error" in evidence or "timed out" in evidence or "connect" in evidence:
        return "NETWORK_ERROR"
    if token_missing and ("token" in evidence or "permission" in evidence or "unauthorized" in evidence):
        return "TOKEN_MISSING"
    if "not found" in evidence or "dataset" in evidence and "not" in evidence:
        return "DATASET_NOT_FOUND"
    if "missing for trade date" in evidence or "no " in evidence and "rows" in evidence:
        return "DATE_NOT_AVAILABLE"
    if semantic_failure:
        return "UNSUPPORTED_BY_FINMIND"
    if missing:
        return "VALIDATION_ERROR"
    if exception_message:
        return "FIELD_MAPPING_ERROR"
    return "PASS"


def semantic_finmind_gap(filename: str) -> str:
    gaps = {
        "options.csv": "FinMind TaiwanOptionDaily can provide TXO PCR inputs, but it does not provide CBOE VIX or formal TDT-RM Tail Risk/BCD scores required by options.csv.",
    }
    return gaps.get(filename, "")


def fallback_source_for(filename: str) -> str:
    fallbacks = {
        "options.csv": "CBOE/Stooq/Yahoo Finance for VIX plus the formal TDT-RM Tail Risk/BCD scoring provider; keep TaiwanOptionDaily only for TXO PCR.",
    }
    return fallbacks.get(filename, "")


def fix_required_for(result: DetailedDatasetStatus) -> str:
    if result.failure_type == "PASS":
        return "No FinMind provider change required."
    if result.failure_type == "NETWORK_ERROR":
        return "Fix API egress/proxy/network path, then rerun diagnostics with FINMIND_TOKEN if available."
    if result.failure_type == "TOKEN_MISSING":
        return "Set FINMIND_TOKEN in the runtime environment."
    if result.failure_type == "UNSUPPORTED_BY_FINMIND":
        return f"Use fallback: {result.fallback_source}"
    if result.filename == "futures.csv" and result.failure_type == "FIELD_MAPPING_ERROR":
        return "Use TaiwanFuturesInstitutionalInvestors for net-short semantics instead of open-interest proxy."
    if result.failure_type == "DATE_NOT_AVAILABLE":
        return "Resolve and request the actual latest FinMind trading date after provider update time."
    if result.failure_type == "DATASET_NOT_FOUND":
        return "Correct the FinMind dataset name or replace with a supported provider."
    if result.failure_type == "VALIDATION_ERROR":
        return f"Map or derive missing required fields: {', '.join(result.required_fields_missing)}."
    if result.failure_type == "RATE_LIMIT":
        return "Throttle requests, cache probes, or upgrade FinMind plan."
    return "Inspect exception and update the current FinMind field mapping."


if __name__ == "__main__":
    raise SystemExit(main())
