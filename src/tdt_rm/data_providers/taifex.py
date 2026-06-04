"""TAIFEX official public-data providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from tdt_rm.public_data_fetchers import PublicDataFetchContext, TAIFEXDailyFXSource, TAIFEXTXFFuturesSource, TAIFEXTXOOptionsSource, load_source_config

from .base import DailyDataProvider, ProviderContext, ProviderResult
from .normalizers import normalize_public_row

_SOURCE_BY_DATASET = {
    "fx": ("taifex_daily_fx", TAIFEXDailyFXSource),
    "futures": ("taifex_txf_futures", TAIFEXTXFFuturesSource),
    "options": ("taifex_txo_options", TAIFEXTXOOptionsSource),
}


@dataclass(frozen=True)
class TAIFEXProvider(DailyDataProvider):
    source_config: str | None = None
    name: str = "TAIFEX_OFFICIAL"
    datasets: tuple[str, ...] = ("fx", "futures", "options")

    def fetch(self, dataset: str, context: ProviderContext) -> ProviderResult:
        if dataset not in _SOURCE_BY_DATASET:
            raise ValueError(f"TAIFEX provider does not support {dataset}")
        source_id, source_cls = _SOURCE_BY_DATASET[dataset]
        result = source_cls(_source_config(source_id, self.source_config)).fetch(
            PublicDataFetchContext(as_of=context.trade_date, main7_symbols=context.main7_symbols, timeout_seconds=context.timeout, retrieved_at=context.fetched_at)
        )
        if not result.success:
            messages = "; ".join(issue.message for issue in result.issues)
            raise RuntimeError(f"status={result.status}" + (f"; {messages}" if messages else ""))
        raw_row = dict(result.rows[0] if result.rows else result.canonical_fields)
        provider_source = f"{self.name}:{result.source_id}"
        row = normalize_public_row(dataset, raw_row, trade_date=context.trade_date, provider_source=provider_source)
        return ProviderResult(dataset, provider_source, result.source_id, row, result.raw_metadata)


def _source_config(source_id: str, source_config: str | None) -> Mapping[str, Any]:
    payload = load_source_config(source_config)
    for item in payload.get("sources", []):
        if isinstance(item, Mapping) and item.get("source_id") == source_id:
            return item
    raise RuntimeError(f"missing public data source config: {source_id}")
