"""Multi-provider daily data layer for TDT-RM."""

from .base import CSV_BY_DATASET, DATASETS, DatasetFetchResult, ProviderContext, ProviderError, ProviderResult
from .finmind import FinMindProvider
from .fx import PublicFXProvider
from .taifex import TAIFEXProvider
from .twse import TWSEProvider
from .yahoo import StooqProvider, YahooProvider

__all__ = [
    "CSV_BY_DATASET",
    "DATASETS",
    "DatasetFetchResult",
    "FinMindProvider",
    "ProviderContext",
    "ProviderError",
    "ProviderResult",
    "PublicFXProvider",
    "StooqProvider",
    "TAIFEXProvider",
    "TWSEProvider",
    "YahooProvider",
]
