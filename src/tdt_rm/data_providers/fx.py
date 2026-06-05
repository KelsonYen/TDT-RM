"""Central-bank/public FX provider aliases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from tdt_rm.public_data_fetchers import CBCDailyFXSource, PublicDataFetchContext, load_source_config

from .base import DailyDataProvider, ProviderContext, ProviderFetchError, ProviderResult
from .normalizers import normalize_public_row
from .taifex import TAIFEXProvider


@dataclass(frozen=True)
class PublicFXProvider(DailyDataProvider):
    """Public USD/TWD provider; currently uses TAIFEX official daily FX endpoint."""

    source_config: str | None = None
    name: str = "PUBLIC_FX"
    datasets: tuple[str, ...] = ("fx",)

    def fetch(self, dataset: str, context: ProviderContext) -> ProviderResult:
        result = TAIFEXProvider(self.source_config).fetch(dataset, context)
        provider_source = result.provider.replace("TAIFEX_OFFICIAL", self.name, 1)
        return ProviderResult(result.dataset, provider_source, result.raw_source, {**dict(result.row), "provider_source": provider_source}, result.raw_metadata)


@dataclass(frozen=True)
class CBCProvider(DailyDataProvider):
    """Official CBC Statistical Database USD/TWD fallback provider."""

    source_config: str | None = None
    name: str = "CBC_OFFICIAL"
    datasets: tuple[str, ...] = ("fx",)

    def fetch(self, dataset: str, context: ProviderContext) -> ProviderResult:
        if dataset != "fx":
            raise ValueError(f"CBC provider does not support {dataset}")
        config = _source_config("cbc_daily_fx", self.source_config)
        result = CBCDailyFXSource(config).fetch(
            PublicDataFetchContext(as_of=context.trade_date, main7_symbols=context.main7_symbols, timeout_seconds=context.timeout, retrieved_at=context.fetched_at)
        )
        if not result.success:
            messages = "; ".join(issue.message for issue in result.issues)
            raise ProviderFetchError(f"status={result.status}" + (f"; {messages}" if messages else ""), result.raw_metadata)
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
