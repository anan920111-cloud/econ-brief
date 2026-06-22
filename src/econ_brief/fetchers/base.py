"""Abstract base class for all paper fetchers."""

import logging
from abc import ABC, abstractmethod
from datetime import date, timedelta

from econ_brief.models.paper import Paper

logger = logging.getLogger(__name__)


class AbstractFetcher(ABC):
    """Interface that all paper fetchers must implement."""

    @abstractmethod
    async def fetch(self, lookback_days: int = 3) -> list[Paper]:
        """Fetch papers published in the last N days.

        Args:
            lookback_days: Number of days to look back from today.

        Returns:
            List of Paper objects (may be empty).
        """
        ...

    @abstractmethod
    def source_name(self) -> str:
        """Human-readable source name for logging and display."""
        ...

    @staticmethod
    def _cutoff_date(lookback_days: int) -> date:
        """Compute the cutoff date for fetching."""
        return date.today() - timedelta(days=lookback_days)
