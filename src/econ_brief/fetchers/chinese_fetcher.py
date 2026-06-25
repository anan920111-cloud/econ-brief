"""Chinese journal fetcher — RSS via curl_cffi (TLS fingerprint impersonation).

CNKI blocks all non-browser TLS fingerprints with HTTP 418. curl_cffi
impersonates Chrome's TLS handshake at the network level, which httpx
cannot do (httpx uses Python's ssl module, detectable by WAFs).

In CI environments, CNKI RSS is skipped automatically (datacenter IPs
are blocked regardless). Local runs from any IP use curl_cffi.
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

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

# curl_cffi browser impersonation targets (rotated to avoid fingerprinting)
_IMPERSONATE_TARGETS = ["chrome124", "chrome120", "safari17_0"]


def _is_ci_environment() -> bool:
    """Detect if we're running in a CI/CD environment."""
    return bool(
        os.environ.get("CI")
        or os.environ.get("GITHUB_ACTIONS")
        or os.environ.get("GITLAB_CI")
        or os.environ.get("JENKINS_URL")
    )


def _force_rss() -> bool:
    """Check if the user explicitly wants RSS even in CI."""
    return os.environ.get("FORCE_CHINESE_RSS", "").lower() in ("true", "1", "yes")


def _fetch_url_with_curl(url: str, timeout: int = 30) -> tuple[int, str]:
    """Fetch a URL using curl_cffi with Chrome TLS impersonation.

    Returns (status_code, response_text).
    Must be called from a thread — curl_cffi is synchronous.
    """
    # Import here so the module can be imported even without curl_cffi
    from curl_cffi import requests as curl_requests

    impersonate = random.choice(_IMPERSONATE_TARGETS)
    headers = {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.9",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }

    resp = curl_requests.get(
        url,
        headers=headers,
        impersonate=impersonate,
        timeout=timeout,
        verify=False,  # CNKI may have SSL quirks
    )
    return resp.status_code, resp.text


def _curl_is_available() -> bool:
    """Check if curl_cffi is installed."""
    try:
        import curl_cffi  # noqa: F401
        return True
    except ImportError:
        return False


class ChineseJournalFetcher(AbstractFetcher):
    """Fetch new papers from Chinese journals via RSS + NCPSSD scraping."""

    def __init__(self, journals: list[dict]):
        self.journals = journals
        self._journal_names = {j["name"]: j for j in journals}

    def source_name(self) -> str:
        return "Chinese Journals"

    async def fetch(self, lookback_days: int = 3) -> list[Paper]:
        cutoff = self._cutoff_date(lookback_days)
        papers: list[Paper] = []

        # Strategy 1: RSS feeds
        in_ci = _is_ci_environment()
        force = _force_rss()

        if in_ci and not force:
            logger.info(
                "CI environment detected — skipping CNKI RSS feeds "
                "(blocked by CNKI anti-bot protection). "
                "Chinese papers will come from OpenAlex only. "
                "Set FORCE_CHINESE_RSS=true to override, "
                "or run locally for full coverage."
            )
        else:
            if in_ci and force:
                logger.info("FORCE_CHINESE_RSS set — attempting CNKI RSS in CI")
            rss_papers = await self._fetch_rss(cutoff)
            papers.extend(rss_papers)
            logger.info("Chinese RSS: %d papers", len(rss_papers))

        # Strategy 2: NCPSSD scraping
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
        """Fetch papers from CNKI RSS feeds using curl_cffi.

        curl_cffi impersonates Chrome's TLS fingerprint, bypassing CNKI's
        WAF that blocks httpx/requests (detectable Python TLS signatures).
        Falls back to httpx if curl_cffi is not installed.
        """
        papers: list[Paper] = []

        if not _curl_is_available():
            logger.warning(
                "curl_cffi not installed — CNKI RSS will likely fail with 418. "
                "Install it with: pip install curl_cffi"
            )
            return await self._fetch_rss_httpx(cutoff)

        for journal_name, rss_url in CHINESE_RSS_URLS.items():
            journal_info = self._journal_names.get(journal_name)
            if not journal_info:
                continue

            try:
                # Run synchronous curl_cffi in a thread to keep the event loop free
                status, text = await asyncio.to_thread(
                    _fetch_url_with_curl, rss_url, timeout=30
                )

                if status == 418:
                    logger.warning(
                        "CNKI still blocking RSS for %s (418) even with TLS "
                        "impersonation. CNKI may be using additional detection.",
                        journal_name,
                    )
                    continue

                if status != 200:
                    logger.warning(
                        "RSS fetch for %s returned HTTP %d", journal_name, status
                    )
                    continue

                feed = feedparser.parse(text)
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

                logger.info(
                    "RSS: %d papers from %s", len(feed.entries), journal_name
                )

            except Exception as e:
                logger.warning("RSS fetch failed for %s: %s", journal_name, e)

            # Polite delay
            await asyncio.sleep(random.uniform(1.0, 2.0))

        return papers

    async def _fetch_rss_httpx(self, cutoff: date) -> list[Paper]:
        """Fallback RSS fetch using httpx (likely to get 418 from CNKI)."""
        papers: list[Paper] = []

        headers = {
            "User-Agent": random.choice(_USER_AGENTS),
            "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.9",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        async with httpx.AsyncClient(
            timeout=30, verify=False, headers=headers, follow_redirects=True,
        ) as client:
            for journal_name, rss_url in CHINESE_RSS_URLS.items():
                journal_info = self._journal_names.get(journal_name)
                if not journal_info:
                    continue
                try:
                    resp = await client.get(rss_url)
                    if resp.status_code == 418:
                        logger.warning(
                            "CNKI blocked RSS fetch for %s (418 anti-bot).",
                            journal_name,
                        )
                        continue
                    resp.raise_for_status()
                    feed = feedparser.parse(resp.text)
                    if feed.bozo:
                        logger.warning("RSS parse error for %s: %s", journal_name, feed.bozo)
                        continue
                    for entry in feed.entries:
                        pub_date = self._parse_feed_date(entry)
                        if pub_date and pub_date < cutoff:
                            continue
                        paper = self._rss_entry_to_paper(entry, journal_info, pub_date)
                        if paper:
                            papers.append(paper)
                except httpx.HTTPStatusError as e:
                    logger.warning("RSS fetch failed for %s: HTTP %d", journal_name, e.response.status_code)
                except Exception as e:
                    logger.warning("RSS fetch failed for %s: %s", journal_name, e)
                await asyncio.sleep(random.uniform(1.0, 2.0))

        return papers

    # ── NCPSSD (unchanged) ────────────────────────────────────────────

    async def _fetch_ncpssd(
        self, journals: list[dict], cutoff: date
    ) -> list[Paper]:
        """Scrape NCPSSD for journal articles."""
        papers: list[Paper] = []

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
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.warning(
                        "NCPSSD scrape failed for %s: %s",
                        journal_info.get("name", "unknown"),
                        e,
                    )

        return papers

    async def _scrape_ncpssd_journal(
        self, client: httpx.AsyncClient, journal_info: dict, cutoff: date,
    ) -> list[Paper]:
        """Attempt to scrape a single journal from NCPSSD."""
        journal_name = journal_info.get("name", "")

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

        soup = BeautifulSoup(resp.text, "lxml")
        papers: list[Paper] = []

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
        title_el = article_el.select_one(".title a, .article-title a, h3 a, h4 a")
        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        if not title:
            return None

        source_url = title_el.get("href", "")
        if source_url and source_url.startswith("/"):
            source_url = f"{NCPSSD_BASE}{source_url}"

        authors: list[Author] = []
        author_el = article_el.select_one(".author, .authors, .article-author")
        if author_el:
            author_text = author_el.get_text(strip=True)
            for name in author_text.replace("，", ",").split(","):
                name = name.strip()
                if name:
                    authors.append(Author(name=name))

        abstract = None
        abstract_el = article_el.select_one(".abstract, .article-abstract, .summary")
        if abstract_el:
            abstract = abstract_el.get_text(strip=True)

        keywords: list[str] = []
        kw_el = article_el.select_one(".keywords, .article-keywords")
        if kw_el:
            kw_text = kw_el.get_text(strip=True)
            kw_text = kw_text.replace("关键词：", "").replace("关键词:", "").replace("Keywords:", "")
            keywords = [k.strip() for k in kw_text.replace("；", ";").split(";") if k.strip()]

        return Paper(
            title=title,
            authors=authors,
            journal=journal_info.get("name"),
            journal_tier=JournalTier.CHINESE_TOP,
            abstract=abstract,
            keywords=keywords,
            language="zh",
            source=PaperSource.CHINESE_JOURNAL,
            source_url=source_url,
        )

    # ── RSS entry mapping (unchanged) ─────────────────────────────────

    def _rss_entry_to_paper(
        self, entry, journal_info: dict, pub_date: date | None
    ) -> Paper | None:
        """Map an RSS feed entry to a Paper."""
        title = entry.get("title", "").strip()
        if not title:
            return None

        authors: list[Author] = []
        author_str = entry.get("author", "")
        if author_str:
            for name in author_str.replace("，", ",").split(","):
                name = name.strip()
                if name:
                    authors.append(Author(name=name))

        abstract = None
        summary = entry.get("summary", "") or entry.get("description", "")
        if summary:
            soup = BeautifulSoup(summary, "lxml")
            abstract = soup.get_text(strip=True)

        source_url = entry.get("link", "")

        return Paper(
            title=title,
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
        time_tuple = entry.get("published_parsed") or entry.get("updated_parsed")
        if time_tuple:
            try:
                return date(time_tuple[0], time_tuple[1], time_tuple[2])
            except (IndexError, ValueError):
                pass

        for date_str in [entry.get("published", ""), entry.get("updated", "")]:
            if date_str:
                try:
                    from datetime import datetime
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
