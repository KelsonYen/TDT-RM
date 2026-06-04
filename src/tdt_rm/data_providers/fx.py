"""Central-bank/public FX provider aliases."""

from __future__ import annotations

from dataclasses import dataclass

from .base import DailyDataProvider, ProviderContext, ProviderResult
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
