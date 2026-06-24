"""Chinese journal fetcher — multi-strategy: RSS (via httpx) + NCPSSD scraping.

CNKI RSS feeds are blocked (HTTP 418) from datacenter IPs (GitHub Actions, etc.).
In CI environments, CNKI RSS is skipped automatically. Set FORCE_CHINESE_RSS=true
to override. Local runs from Chinese residential IPs should work normally.
"""

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import asyncio
import logging
import os
import random
from datetime import date, timedelta

import feedparser
import httpx
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from econ_brief.constants import NCPSSD_BASE, CHINESE_RSS_URLS
from econ_brief.fetchers.base import AbstractFetcher
from econ_brief.models.paper import Author, Paper, PaperSource, JournalTier

logger = logging.getLogger(__name__)

# Browser-like User-Agent pool to rotate through — avoids CNKI 418 blocking
_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]


def _is_ci_environment() -> bool:
    """Detect if we're running in a CI/CD environment."""
    return bool(
        os.environ.get("CI")  # Generic CI indicator
        or os.environ.get("GITHUB_ACTIONS")  # GitHub Actions
        or os.environ.get("GITLAB_CI")  # GitLab CI
        or os.environ.get("JENKINS_URL")  # Jenkins
    )


def _force_rss() -> bool:
    """Check if the user explicitly wants RSS even in CI."""
    return os.environ.get("FORCE_CHINESE_RSS", "").lower() in ("true", "1", "yes")


class ChineseJournalFetcher(AbstractFetcher):
    """Fetch new papers from Chinese journals via NCPSSD and RSS.

    Strategy (priority order):
    1. RSS feeds (where available — fastest, most reliable)
    2. NCPSSD scraping (free, covers ~2400 journals)
    3. (Future) Direct journal TOC page crawling

    Note: OpenAlex also covers some Chinese journals; that is handled
    separately by the OpenAlexFetcher. This fetcher is supplementary.
    """

    def __init__(self, journals: list[dict]):
        """
        Args:
            journals: List of Chinese journal configs with keys: name, issn, name_en.
        """
        self.journals = journals
        # Build lookup by name for RSS URLs
        self._journal_names = {j["name"]: j for j in journals}

    def source_name(self) -> str:
        return "Chinese Journals"

    async def fetch(self, lookback_days: int = 3) -> list[Paper]:
        cutoff = self._cutoff_date(lookback_days)
        papers: list[Paper] = []

        # Strategy 1: RSS feeds (CNKI — blocked in CI environments)
        in_ci = _is_ci_environment()
        force = _force_rss()

        if in_ci and not force:
            logger.info(
                "CI environment detected — skipping CNKI RSS feeds "
                "(blocked by CNKI anti-bot protection). "
                "Chinese papers will come from OpenAlex only. "
                "Set FORCE_CHINESE_RSS=true to override, "
                "or run locally from a Chinese IP for full coverage."
            )
        else:
            if in_ci and force:
                logger.info("FORCE_CHINESE_RSS set — attempting CNKI RSS in CI")
            rss_papers = await self._fetch_rss(cutoff)
            papers.extend(rss_papers)
            logger.info("Chinese RSS: %d papers", len(rss_papers))

        # Strategy 2: NCPSSD scraping (for journals not covered by RSS)
        rss_covered = set(CHINESE_RSS_URLS.keys())
        ncpssd_journals = [
            j for j in self.journals if j["name"] not in rss_covered
        ]
        if ncpssd_journals:
            ncpssd_papers = await self._fetch_ncpssd(ncpssd_journals, cutoff)
            papers.extend(ncpssd_papers)
            logger.info("Chinese NCPSSD: %d papers", len(ncpssd_papers))

        return papers

    async def _fetch_rss(self, cutoff: date) -> list[Paper]:
        """Fetch papers from Chinese journal RSS feeds using httpx.

        Uses browser-like User-Agent headers to avoid CNKI 418 anti-bot
        responses. feedparser.parse() is NOT called directly on URLs —
        the feed content is fetched via httpx first, then parsed locally.
        """
        papers: list[Paper] = []

        # Use a single httpx client with browser-mimicking headers
        headers = {
            "User-Agent": random.choice(_USER_AGENTS),
            "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.9",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }

        async with httpx.AsyncClient(
            timeout=30,
            verify=False,  # Disable SSL verification for CNKI compatibility
            headers=headers,
            follow_redirects=True,
            http2=True,  # CNKI supports HTTP/2
        ) as client:
            for journal_name, rss_url in CHINESE_RSS_URLS.items():
                journal_info = self._journal_names.get(journal_name)
                if not journal_info:
                    continue

                try:
                    resp = await client.get(rss_url)
                    if resp.status_code == 418:
                        logger.warning(
                            "CNKI blocked RSS fetch for %s (418 anti-bot). "
                            "This is CNKI's restriction, not a network issue. "
                            "Consider using alternative sources.",
                            journal_name,
                        )
                        continue
                    resp.raise_for_status()

                    # Parse the fetched XML/feed content locally
                    feed = feedparser.parse(resp.text)
                    if feed.bozo:
                        logger.warning(
                            "RSS parse error for %s: %s", journal_name, feed.bozo
                        )
                        continue

                    for entry in feed.entries:
                        pub_date = self._parse_feed_date(entry)
                        if pub_date and pub_date < cutoff:
                            continue

                        paper = self._rss_entry_to_paper(entry, journal_info, pub_date)
                        if paper:
                            papers.append(paper)

                    logger.debug("RSS: %d papers from %s", len(feed.entries), journal_name)

                except httpx.HTTPStatusError as e:
                    logger.warning(
                        "RSS fetch failed for %s: HTTP %d — %s",
                        journal_name,
                        e.response.status_code,
                        e,
                    )
                except httpx.RequestError as e:
                    logger.warning(
                        "RSS fetch failed for %s: network error — %s",
                        journal_name,
                        e,
                    )
                except Exception as e:
                    logger.warning("RSS fetch failed for %s: %s", journal_name, e)

                # Polite delay between feeds to avoid rate limiting
                await asyncio.sleep(random.uniform(1.0, 2.0))

        return papers

    async def _fetch_ncpssd(
        self, journals: list[dict], cutoff: date
    ) -> list[Paper]:
        """Scrape NCPSSD for journal articles.

        Note: NCPSSD uses 'gch' codes (journal identifiers) that need to be
        manually mapped. For now, this is a best-effort attempt. Journals
        that are also covered by OpenAlex will have coverage there.
        """
        papers: list[Paper] = []

        # NCPSSD journal listing endpoint
        # We attempt to find each journal by searching NCPSSD
        async with httpx.AsyncClient(
            timeout=30,
            headers={
                "User-Agent": random.choice(_USER_AGENTS),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        ) as client:
            for journal_info in journals:
                try:
                    journal_papers = await self._scrape_ncpssd_journal(
                        client, journal_info, cutoff
                    )
                    papers.extend(journal_papers)
                    await asyncio.sleep(2)  # Polite delay between journals
                except Exception as e:
                    logger.warning(
                        "NCPSSD scrape failed for %s: %s",
                        journal_info.get("name", "unknown"),
                        e,
                    )

        return papers

    async def _scrape_ncpssd_journal(
        self,
        client: httpx.AsyncClient,
        journal_info: dict,
        cutoff: date,
    ) -> list[Paper]:
        """Attempt to scrape a single journal from NCPSSD.

        This is a best-effort implementation. NCPSSD may change its HTML
        structure, require authentication, or block automated access.
        """
        journal_name = journal_info.get("name", "")

        # Try searching for the journal on NCPSSD
        search_url = f"{NCPSSD_BASE}/journal/search"
        try:
            resp = await client.get(
                search_url,
                params={"keyword": journal_name},
                follow_redirects=True,
            )
            if resp.status_code != 200:
                logger.debug("NCPSSD search returned %d for %s", resp.status_code, journal_name)
                return []
        except httpx.HTTPError as e:
            logger.debug("NCPSSD search request failed for %s: %s", journal_name, e)
            return []

        # Parse search results to find the journal page
        soup = BeautifulSoup(resp.text, "lxml")
        papers: list[Paper] = []

        # Attempt to find article listings (selector will need tuning)
        for article_el in soup.select(".article-item, .paper-item, .list-item"):
            try:
                paper = self._parse_ncpssd_article(article_el, journal_info)
                if paper and (not paper.publication_date or paper.publication_date >= cutoff):
                    papers.append(paper)
            except Exception:
                continue

        return papers

    def _parse_ncpssd_article(
        self, article_el, journal_info: dict
    ) -> Paper | None:
        """Parse an NCPSSD article element into a Paper."""
        # Title
        title_el = (
            article_el.select_one(".title a, .article-title a, h3 a, h4 a")
        )
        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        if not title:
            return None

        source_url = title_el.get("href", "")
        if source_url and source_url.startswith("/"):
            source_url = f"{NCPSSD_BASE}{source_url}"

        # Authors
        authors: list[Author] = []
        author_el = article_el.select_one(".author, .authors, .article-author")
        if author_el:
            author_text = author_el.get_text(strip=True)
            for name in author_text.replace("，", ",").split(","):
                name = name.strip()
                if name:
                    authors.append(Author(name=name))

        # Abstract
        abstract = None
        abstract_el = article_el.select_one(".abstract, .article-abstract, .summary")
        if abstract_el:
            abstract = abstract_el.get_text(strip=True)

        # Keywords
        keywords: list[str] = []
        kw_el = article_el.select_one(".keywords, .article-keywords")
        if kw_el:
            kw_text = kw_el.get_text(strip=True)
            # Remove "关键词:" / "Keywords:" prefix
            kw_text = kw_text.replace("关键词：", "").replace("关键词:", "").replace("Keywords:", "")
            keywords = [k.strip() for k in kw_text.replace("；", ";").split(";") if k.strip()]

        return Paper(
            title=title,
            title_en=journal_info.get("name_en"),
            authors=authors,
            journal=journal_info.get("name"),
            journal_tier=JournalTier.CHINESE_TOP,
            abstract=abstract,
            keywords=keywords,
            language="zh",
            source=PaperSource.CHINESE_JOURNAL,
            source_url=source_url,
        )

    def _rss_entry_to_paper(
        self, entry, journal_info: dict, pub_date: date | None
    ) -> Paper | None:
        """Map an RSS feed entry to a Paper."""
        title = entry.get("title", "").strip()
        if not title:
            return None

        # Authors — RSS entries often have author field
        authors: list[Author] = []
        author_str = entry.get("author", "")
        if author_str:
            for name in author_str.replace("，", ",").split(","):
                name = name.strip()
                if name:
                    authors.append(Author(name=name))

        # Abstract / summary
        abstract = None
        summary = entry.get("summary", "") or entry.get("description", "")
        if summary:
            # Strip HTML tags
            soup = BeautifulSoup(summary, "lxml")
            abstract = soup.get_text(strip=True)

        source_url = entry.get("link", "")

        return Paper(
            title=title,
            title_en=journal_info.get("name_en"),
            authors=authors,
            journal=journal_info.get("name"),
            journal_tier=JournalTier.CHINESE_TOP,
            publication_date=pub_date,
            abstract=abstract,
            language="zh",
            source=PaperSource.CHINESE_JOURNAL,
            source_url=source_url,
        )

    @staticmethod
    def _parse_feed_date(entry) -> date | None:
        """Parse date from a feed entry."""
        # Try published_parsed (struct_time)
        time_tuple = entry.get("published_parsed") or entry.get("updated_parsed")
        if time_tuple:
            try:
                return date(time_tuple[0], time_tuple[1], time_tuple[2])
            except (IndexError, ValueError):
                pass

        # Try string dates
        for date_str in [entry.get("published", ""), entry.get("updated", "")]:
            if date_str:
                try:
                    from datetime import datetime
                    # Try various formats
                    for fmt in [
                        "%Y-%m-%dT%H:%M:%S%z",
                        "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%d",
                    ]:
                        try:
                            return datetime.strptime(date_str[:19], fmt).date()
                        except ValueError:
                            continue
                except Exception:
                    pass

        return None
