"""Provider abstractions for automated daily TDT-RM CSV generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Protocol

DATASETS: tuple[str, ...] = ("price", "foreign_flow", "fx", "breadth", "futures", "options", "leadership", "margin")
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
    allow_finmind_live: bool = False


@dataclass(frozen=True)
class ProviderResult:
    dataset: str
    provider: str
    raw_source: str
    row: Mapping[str, Any]
    raw_metadata: Mapping[str, Any] = field(default_factory=dict)


class ProviderFetchError(RuntimeError):
    """Provider failure that preserves raw diagnostics for health artifacts."""

    def __init__(self, message: str, metadata: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.metadata = dict(metadata or {})


@dataclass(frozen=True)
class ReconciliationCheck:
    name: str
    status: str
    message: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "passed"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class ProviderHealth:
    provider: str
    dataset: str
    status: str
    attempted: bool = True
    selected: bool = False
    failure_reason: str = ""
    output_path: str | None = None
    checks: tuple[ReconciliationCheck, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "dataset": self.dataset,
            "status": self.status,
            "attempted": self.attempted,
            "selected": self.selected,
            "failure_reason": self.failure_reason,
            "output_path": self.output_path,
            "checks": [check.as_dict() for check in self.checks],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class DatasetFetchResult:
    dataset: str
    status: str
    provider_used: str | None = None
    output_path: str | None = None
    failed_providers: tuple[ProviderError, ...] = ()
    provider_health: tuple[ProviderHealth, ...] = ()
    reconciliation_checks: tuple[ReconciliationCheck, ...] = ()
    validation_errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == "success" and bool(self.provider_used) and bool(self.output_path) and not self.validation_errors and all(check.ok for check in self.reconciliation_checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_used": self.provider_used,
            "status": self.status,
            "output_path": self.output_path,
            "failed_providers": [error.as_dict() for error in self.failed_providers],
            "provider_health": [health.as_dict() for health in self.provider_health],
            "reconciliation_checks": [check.as_dict() for check in self.reconciliation_checks],
            "validation_errors": list(self.validation_errors),
        }


class DailyDataProvider(Protocol):
    name: str
    datasets: tuple[str, ...]

    def fetch(self, dataset: str, context: ProviderContext) -> ProviderResult:
        """Fetch and normalize one dataset to the strict daily input schema."""
