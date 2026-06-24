"""NBER working paper fetcher — RSS feed with JSON API fallback.

RSS (https://www.nber.org/rss/new.xml) is more likely to work from CI
than the JSON API, which blocks datacenter IPs.
"""

import asyncio
import logging
import random
import re
from datetime import date, datetime, timedelta

import feedparser
import httpx
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    RetryError,
)

from econ_brief.constants import NBER_API_URL
from econ_brief.fetchers.base import AbstractFetcher
from econ_brief.models.paper import Author, Paper, PaperSource, JournalTier

logger = logging.getLogger(__name__)

NBER_RSS_URL = "https://www.nber.org/rss/new.xml"

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


class NBERFetcher(AbstractFetcher):
    """Fetch new NBER working papers via RSS (primary) or JSON API (fallback)."""

    def source_name(self) -> str:
        return "NBER"

    async def fetch(self, lookback_days: int = 3) -> list[Paper]:
        cutoff = self._cutoff_date(lookback_days)
        headers = {
            "User-Agent": random.choice(_USER_AGENTS),
            "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.9",
            "Accept-Language": "en-US,en;q=0.9",
        }

        async with httpx.AsyncClient(
            timeout=30, headers=headers, follow_redirects=True,
        ) as client:
            # Strategy 1: RSS feed (more CI-friendly)
            papers = await self._fetch_rss(client, cutoff)
            if papers:
                logger.info("NBER RSS: %d new working papers", len(papers))
                return papers

            # Strategy 2: JSON API fallback
            logger.info("NBER RSS empty/unavailable, trying JSON API...")
            papers = await self._fetch_api(client, cutoff)
            logger.info("NBER API: %d new working papers", len(papers))
            return papers

    # ── RSS strategy ──────────────────────────────────────────────────

    async def _fetch_rss(
        self, client: httpx.AsyncClient, cutoff: date
    ) -> list[Paper]:
        """Fetch NBER papers from RSS feed."""
        papers: list[Paper] = []

        try:
            resp = await client.get(NBER_RSS_URL)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.warning(
                "NBER RSS returned HTTP %d (may block CI IPs)",
                e.response.status_code,
            )
            return []
        except httpx.RequestError as e:
            logger.warning("NBER RSS network error: %s", e)
            return []

        feed = feedparser.parse(resp.text)
        if feed.bozo:
            logger.warning("NBER RSS parse error: %s", feed.bozo)
            return []

        for entry in feed.entries:
            pub_date = self._parse_rss_date(entry)
            if pub_date and pub_date < cutoff:
                continue

            paper = self._rss_entry_to_paper(entry, pub_date)
            if paper:
                papers.append(paper)

        return papers

    def _rss_entry_to_paper(self, entry, pub_date: date | None) -> Paper | None:
        """Map an RSS feed entry to a Paper."""
        title = entry.get("title", "").strip()
        if not title:
            return None

        # NBER ID: extract from link
        link = entry.get("link", "")
        nber_id = None
        if link:
            parts = link.rstrip("/").split("/")
            if parts:
                nber_id = parts[-1]
                if not nber_id.startswith("w"):
                    nber_id = None

        # Authors: dc:creator or author field
        authors: list[Author] = []
        author_str = entry.get("author", "") or entry.get("dc_creator", "")
        if author_str:
            for name in re.split(r",\s*|\s+and\s+", author_str):
                name = name.strip()
                if name:
                    authors.append(Author(name=name))

        # Abstract / description
        abstract = None
        desc = entry.get("summary", "") or entry.get("description", "")
        if desc:
            soup = BeautifulSoup(desc, "lxml")
            abstract = soup.get_text(strip=True)

        source_url = link or None

        # PDF URL
        pdf_url = None
        if nber_id:
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
            publication_date=pub_date,
            abstract=abstract,
            language="en",
            source=PaperSource.NBER,
            source_url=source_url,
            pdf_url=pdf_url,
            is_open_access=True,
        )

    @staticmethod
    def _parse_rss_date(entry) -> date | None:
        """Parse date from RSS entry."""
        time_tuple = entry.get("published_parsed") or entry.get("updated_parsed")
        if time_tuple:
            try:
                return date(time_tuple[0], time_tuple[1], time_tuple[2])
            except (IndexError, ValueError):
                pass

        for date_str in [entry.get("published", ""), entry.get("updated", "")]:
            if date_str:
                try:
                    for fmt in [
                        "%Y-%m-%dT%H:%M:%S%z",
                        "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%d",
                        "%a, %d %b %Y %H:%M:%S %z",
                    ]:
                        try:
                            return datetime.strptime(date_str.strip(), fmt).date()
                        except ValueError:
                            continue
                except Exception:
                    pass

        return None

    # ── JSON API fallback ─────────────────────────────────────────────

    async def _fetch_api(
        self, client: httpx.AsyncClient, cutoff: date
    ) -> list[Paper]:
        """Fetch NBER papers from JSON API (paginated)."""
        papers: list[Paper] = []
        page = 1

        while True:
            try:
                data = await self._fetch_api_page(client, page)
            except RetryError as e:
                cause = e.__cause__ if e.__cause__ else e
                if isinstance(cause, httpx.HTTPStatusError):
                    logger.warning(
                        "NBER API returned HTTP %d (likely blocking CI IPs).",
                        cause.response.status_code,
                    )
                else:
                    logger.warning("NBER API fetch failed after retries: %s", cause)
                break
            except httpx.HTTPStatusError as e:
                logger.warning("NBER API page %d HTTP %d", page, e.response.status_code)
                break
            except Exception as e:
                logger.warning("NBER API page %d fetch failed: %s", page, e)
                break

            results = data.get("results", [])
            if not results:
                break

            found_old = False
            for item in results:
                pub_date = self._parse_api_date(item.get("displaydate", ""))
                if pub_date is None:
                    paper = self._api_item_to_paper(item)
                    papers.append(paper)
                    continue
                if pub_date < cutoff:
                    found_old = True
                    continue
                paper = self._api_item_to_paper(item)
                paper.publication_date = pub_date
                papers.append(paper)

            if found_old:
                break

            page += 1
            await asyncio.sleep(0.5)

        return papers

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(httpx.HTTPError),
    )
    async def _fetch_api_page(self, client: httpx.AsyncClient, page: int) -> dict:
        """Fetch a single page of NBER API results."""
        response = await client.get(
            NBER_API_URL,
            params={"page": page, "perPage": 100, "sortBy": "public_date"},
        )
        response.raise_for_status()
        return response.json()

    def _api_item_to_paper(self, item: dict) -> Paper:
        """Map an NBER API result item to our unified Paper model."""
        title = item.get("title", "").strip()
        nber_id = str(item.get("url", "")).split("/")[-1] if item.get("url") else None

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

        pdf_url = None
        if nber_id:
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
    def _parse_api_date(date_str: str) -> date | None:
        """Parse NBER API date format (e.g., 'June 2026' or '2026-06-15')."""
        if not date_str:
            return None
        try:
            return date.fromisoformat(date_str[:10])
        except (ValueError, TypeError):
            pass
        try:
            return datetime.strptime(date_str, "%B %Y").date()
        except ValueError:
            pass
        return None
