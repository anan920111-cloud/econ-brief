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
    email: str | None = None,
) -> list[Paper]:
    """Run all fetchers concurrently and collect results.

    Args:
        intl_journals: List of international journal configs (with issn, name, tier).
        chinese_journals: List of Chinese journal configs.
        lookback_days: How many days back to fetch.
        email: Email for OpenAlex polite pool.

    Returns:
        Combined list of all fetched Paper objects.
    """
    fetchers: list[AbstractFetcher] = [
        OpenAlexFetcher(
            journals=intl_journals + chinese_journals,
            email=email,
        ),
        ArxivFetcher(),
        NBERFetcher(),
        ChineseJournalFetcher(journals=chinese_journals),
    ]

    tasks = [asyncio.ensure_future(f.fetch(lookback_days)) for f in fetchers]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_papers: list[Paper] = []
    for fetcher, result in zip(fetchers, results):
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
