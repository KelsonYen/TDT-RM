"""TWSE official public-data providers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from typing import Any, Mapping

from tdt_rm.public_data_fetchers import (
    PublicDataFetchContext,
    TWSEFMTQIKPriceSource,
    TWSEMarketBreadthSource,
    TWSEMain7LeadershipSource,
    TWSET86ForeignFlowSource,
    load_source_config,
)

from .base import DailyDataProvider, ProviderContext, ProviderResult
from .normalizers import normalize_public_row

_SOURCE_BY_DATASET = {
    "price": ("twse_fmtqik_price", TWSEFMTQIKPriceSource),
    "foreign_flow": ("twse_t86_foreign_flow", TWSET86ForeignFlowSource),
    "breadth": ("twse_mi_index_breadth", TWSEMarketBreadthSource),
    "leadership": ("twse_main7_leadership", TWSEMain7LeadershipSource),
}


@dataclass(frozen=True)
class TWSEProvider(DailyDataProvider):
    """Provider that fetches official TWSE public endpoints before vendor fallbacks."""

    source_config: str | None = None
    name: str = "TWSE_OFFICIAL"
    datasets: tuple[str, ...] = ("price", "foreign_flow", "breadth", "leadership")

    def fetch(self, dataset: str, context: ProviderContext) -> ProviderResult:
        if dataset not in _SOURCE_BY_DATASET:
            raise ValueError(f"TWSE provider does not support {dataset}")
        source_id, source_cls = _SOURCE_BY_DATASET[dataset]
        config = _source_config(source_id, self.source_config)
        result = source_cls(config).fetch(_public_context(context))
        if not result.success:
            raise RuntimeError(_failure_message(result.status, result.issues))
        raw_row = dict(result.rows[0] if result.rows else result.canonical_fields)
        provider_source = f"{self.name}:{result.source_id}"
        row = normalize_public_row(dataset, raw_row, trade_date=context.trade_date, provider_source=provider_source)
        return ProviderResult(dataset, provider_source, result.source_id, row, result.raw_metadata)


def _public_context(context: ProviderContext) -> PublicDataFetchContext:
    return PublicDataFetchContext(
        as_of=context.trade_date,
        main7_symbols=context.main7_symbols,
        timeout_seconds=context.timeout,
        retrieved_at=context.fetched_at.replace(tzinfo=UTC) if context.fetched_at.tzinfo is None else context.fetched_at,
    )


def _source_config(source_id: str, source_config: str | None) -> Mapping[str, Any]:
    payload = load_source_config(source_config)
    for item in payload.get("sources", []):
        if isinstance(item, Mapping) and item.get("source_id") == source_id:
            return item
    raise RuntimeError(f"missing public data source config: {source_id}")


def _failure_message(status: str, issues: tuple[Any, ...]) -> str:
    messages = "; ".join(str(getattr(issue, "message", issue)) for issue in issues)
    return f"status={status}" + (f"; {messages}" if messages else "")
