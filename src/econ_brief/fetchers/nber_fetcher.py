"""NBER working paper fetcher via undocumented JSON API."""

import asyncio
import logging
import random
from datetime import date, timedelta

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from econ_brief.constants import NBER_API_URL
from econ_brief.fetchers.base import AbstractFetcher
from econ_brief.models.paper import Author, Paper, PaperSource, JournalTier

logger = logging.getLogger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


class NBERFetcher(AbstractFetcher):
    """Fetch new NBER working papers."""

    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    def source_name(self) -> str:
        return "NBER"

    async def fetch(self, lookback_days: int = 3) -> list[Paper]:
        cutoff = self._cutoff_date(lookback_days)
        papers: list[Paper] = []

        async with httpx.AsyncClient(
            timeout=30,
            headers={
                "User-Agent": random.choice(_USER_AGENTS),
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
            },
        ) as client:
            page = 1
            while True:
                try:
                    data = await self._fetch_page(client, page)
                except httpx.HTTPStatusError as e:
                    logger.warning(
                        "NBER page %d returned HTTP %d (may be blocking CI IPs)",
                        page,
                        e.response.status_code,
                    )
                    break
                except Exception as e:
                    logger.warning("NBER page %d fetch failed: %s", page, e)
                    break

                results = data.get("results", [])
                if not results:
                    break

                found_old = False
                for item in results:
                    pub_date = self._parse_date(item.get("displaydate", ""))
                    if pub_date is None:
                        # If no date, include anyway
                        paper = self._item_to_paper(item)
                        papers.append(paper)
                        continue

                    if pub_date < cutoff:
                        found_old = True
                        continue

                    paper = self._item_to_paper(item)
                    paper.publication_date = pub_date
                    papers.append(paper)

                if found_old:
                    # Results are sorted descending; stop on first old paper
                    break

                page += 1
                await asyncio.sleep(0.5)  # Polite delay

        logger.info("NBER: %d new working papers", len(papers))
        return papers

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(httpx.HTTPError),
    )
    async def _fetch_page(self, client: httpx.AsyncClient, page: int) -> dict:
        """Fetch a single page of NBER results."""
        response = await client.get(
            NBER_API_URL,
            params={
                "page": page,
                "perPage": 100,
                "sortBy": "public_date",
            },
        )
        response.raise_for_status()
        return response.json()

    def _item_to_paper(self, item: dict) -> Paper:
        """Map an NBER API result item to our unified Paper model."""
        title = item.get("title", "").strip()
        nber_id = str(item.get("url", "")).split("/")[-1] if item.get("url") else None

        # Authors: NBER provides as a string "Author1, Author2, Author3"
        authors: list[Author] = []
        author_str = item.get("authors", "")
        if author_str:
            for name in author_str.split(","):
                name = name.strip()
                if name:
                    authors.append(Author(name=name))

        abstract = item.get("abstract", "").strip() or None
        source_url = item.get("url")
        if source_url and source_url.startswith("/"):
            source_url = f"https://www.nber.org{source_url}"

        # PDF URL
        pdf_url = None
        if nber_id:
            # Pattern: https://www.nber.org/system/files/working_papers/w{id}/w{id}.pdf
            pdf_url = (
                f"https://www.nber.org/system/files/"
                f"working_papers/w{nber_id}/w{nber_id}.pdf"
            )

        return Paper(
            title=title,
            nber_id=nber_id,
            authors=authors,
            journal="NBER Working Paper",
            journal_tier=JournalTier.PREPRINT,
            abstract=abstract,
            language="en",
            source=PaperSource.NBER,
            source_url=source_url,
            pdf_url=pdf_url,
            is_open_access=True,
        )

    @staticmethod
    def _parse_date(date_str: str) -> date | None:
        """Parse NBER date format (e.g., 'June 2026' or '2026-06-15')."""
        if not date_str:
            return None

        # Try ISO format first
        try:
            return date.fromisoformat(date_str[:10])
        except (ValueError, TypeError):
            pass

        # Try "Month YYYY" format
        try:
            from datetime import datetime

            dt = datetime.strptime(date_str, "%B %Y")
            return dt.date()
        except ValueError:
            pass

        return None
