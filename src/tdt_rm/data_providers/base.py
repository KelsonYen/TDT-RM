"""Provider abstractions for automated daily TDT-RM CSV generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Protocol

DATASETS: tuple[str, ...] = ("price", "foreign_flow", "fx", "breadth", "futures", "options", "leadership")
CSV_BY_DATASET = {dataset: f"{dataset}.csv" for dataset in DATASETS}
REAL_SOURCE_TYPE = "REAL_PROVIDER"


@dataclass(frozen=True)
class ProviderError:
    provider: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"provider": self.provider, "message": self.message}


@dataclass(frozen=True)
class ProviderContext:
    trade_date: date
    fetched_at: datetime
    lookback_days: int = 180
    timeout: int = 30
    sleep_seconds: float = 0.25
    main7_symbols: tuple[str, ...] = ()
    main7_config: str | Path = "config/main7_symbols.json"


@dataclass(frozen=True)
class ProviderResult:
    dataset: str
    provider: str
    raw_source: str
    row: Mapping[str, Any]
    raw_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DatasetFetchResult:
    dataset: str
    status: str
    provider_used: str | None = None
    output_path: str | None = None
    failed_providers: tuple[ProviderError, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == "success" and bool(self.provider_used) and bool(self.output_path)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_used": self.provider_used,
            "status": self.status,
            "output_path": self.output_path,
            "failed_providers": [error.as_dict() for error in self.failed_providers],
        }


class DailyDataProvider(Protocol):
    name: str
    datasets: tuple[str, ...]

    def fetch(self, dataset: str, context: ProviderContext) -> ProviderResult:
        """Fetch and normalize one dataset to the strict daily input schema."""
