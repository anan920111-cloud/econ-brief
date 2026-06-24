"""Data fetchers for various paper sources."""

import asyncio
import logging
from datetime import date, timedelta

from econ_brief.fetchers.base import AbstractFetcher
from econ_brief.fetchers.openalex_fetcher import OpenAlexFetcher
from econ_brief.fetchers.arxiv_fetcher import ArxivFetcher
from econ_brief.fetchers.nber_fetcher import NBERFetcher
from econ_brief.fetchers.chinese_fetcher import ChineseJournalFetcher
from econ_brief.models.paper import Paper

logger = logging.getLogger(__name__)


async def fetch_all(
    intl_journals: list[dict],
    chinese_journals: list[dict],
    lookback_days: int = 3,
    lookback_days_zh: int = 30,
    email: str | None = None,
) -> list[Paper]:
    """Run all fetchers concurrently and collect results.

    Args:
        intl_journals: List of international journal configs.
        chinese_journals: List of Chinese journal configs.
        lookback_days: Days back for international sources.
        lookback_days_zh: Days back for Chinese journals (longer window).
        email: Email for OpenAlex polite pool.

    Returns:
        Combined list of all fetched Paper objects.
    """
    fetchers: list[tuple[AbstractFetcher, int]] = [
        (OpenAlexFetcher(journals=intl_journals + chinese_journals, email=email), lookback_days),
        (ArxivFetcher(), lookback_days),
        (NBERFetcher(), lookback_days),
        (ChineseJournalFetcher(journals=chinese_journals), lookback_days_zh),
    ]

    tasks = [asyncio.ensure_future(f.fetch(days)) for f, days in fetchers]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_papers: list[Paper] = []
    for (fetcher, _days), result in zip(fetchers, results):
        if isinstance(result, Exception):
            logger.error(
                "Fetcher %s failed: %s", fetcher.source_name(), result
            )
        else:
            logger.info(
                "Fetcher %s returned %d papers",
                fetcher.source_name(),
                len(result),
            )
            all_papers.extend(result)

    logger.info("Total fetched: %d papers from all sources", len(all_papers))
    return all_papers
