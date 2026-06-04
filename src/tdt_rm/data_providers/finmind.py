"""FinMind fallback provider for the multi-provider daily layer.

This provider is tagged as external-network-required: it performs live HTTPS
requests and must not be assumed available in Codex/runtime environments.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Callable

from .base import DailyDataProvider, ProviderContext, ProviderResult

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from fetch_daily_data_finmind import (  # type: ignore  # noqa: E402
    FinMindClient,
    build_breadth,
    build_finmind_opener,
    build_foreign_flow,
    build_futures,
    build_fx,
    build_leadership,
    build_options,
    build_price,
)


@dataclass(frozen=True)
class FinMindProvider(DailyDataProvider):
    """FinMind fallback. It is intentionally last and external-network-required."""

    network_requirement: str = "external-network-required"

    token: str | None = None
    name: str = "FINMIND_FALLBACK"
    datasets: tuple[str, ...] = ("price", "foreign_flow", "fx", "breadth", "futures", "options", "leadership")

    def fetch(self, dataset: str, context: ProviderContext) -> ProviderResult:
        token = self.token or os.environ.get("FINMIND_TOKEN") or os.environ.get("FINMIND_API_TOKEN")
        client = FinMindClient(token, timeout=context.timeout, sleep_seconds=context.sleep_seconds, opener=None)
        start = context.trade_date - timedelta(days=context.lookback_days)
        fetched_at = context.fetched_at.isoformat().replace("+00:00", "Z")
        builders: dict[str, Callable[[], tuple[dict, str]]] = {
            "price": lambda: build_price(client, context.trade_date, start, fetched_at),
            "foreign_flow": lambda: build_foreign_flow(client, context.trade_date, start, fetched_at),
            "fx": lambda: build_fx(client, context.trade_date, start, fetched_at),
            "breadth": lambda: build_breadth(client, context.trade_date, start, fetched_at),
            "futures": lambda: build_futures(client, context.trade_date, start, fetched_at),
            "options": lambda: build_options(client, context.trade_date, start, fetched_at),
            "leadership": lambda: build_leadership(client, context.trade_date, start, fetched_at, context.main7_symbols),
        }
        if dataset not in builders:
            raise ValueError(f"FinMind provider does not support {dataset}")
        row, raw_source = builders[dataset]()
        provider_source = f"{self.name}:{raw_source}"
        row = {**row, "provider_source": provider_source}
        return ProviderResult(
            dataset,
            provider_source,
            raw_source,
            row,
            {
                "finmind_token_present": bool(token),
                "network_requirement": self.network_requirement,
            },
        )
