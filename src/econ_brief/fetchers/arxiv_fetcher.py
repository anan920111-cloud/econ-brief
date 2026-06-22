"""arXiv API fetcher for economics preprints."""

import logging
from datetime import date, timedelta, datetime

import arxiv

from econ_brief.constants import ARXIV_CATEGORIES
from econ_brief.fetchers.base import AbstractFetcher
from econ_brief.models.paper import Author, Paper, PaperSource, JournalTier

logger = logging.getLogger(__name__)


class ArxivFetcher(AbstractFetcher):
    """Fetch new economics papers from arXiv."""

    def __init__(self, categories: list[str] | None = None):
        """
        Args:
            categories: arXiv categories to monitor. Defaults to econ.GN, econ.EM, econ.TH.
        """
        self.categories = categories or ARXIV_CATEGORIES

    def source_name(self) -> str:
        return "arXiv"

    async def fetch(self, lookback_days: int = 3) -> list[Paper]:
        cutoff = self._cutoff_date(lookback_days)

        # Build query: all econ categories, newest first
        query = " OR ".join(f"cat:{cat}" for cat in self.categories)

        client = arxiv.Client(
            page_size=100,
            delay_seconds=3.0,
            num_retries=3,
        )

        search = arxiv.Search(
            query=query,
            max_results=200,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )

        papers: list[Paper] = []
        try:
            for result in client.results(search):
                # Client-side date filter (more reliable than API filter)
                pub_date = result.published.date()
                if pub_date < cutoff:
                    # Results are sorted descending; stop when we pass the cutoff
                    continue

                paper = self._result_to_paper(result)
                papers.append(paper)

                if len(papers) >= 150:
                    break

        except Exception as e:
            logger.error("arXiv fetch error: %s", e)
            raise

        logger.info("arXiv: %d new papers in econ categories", len(papers))
        return papers

    def _result_to_paper(self, result: arxiv.Result) -> Paper:
        """Map an arxiv.Result to our unified Paper model."""
        # Authors
        authors: list[Author] = []
        for a in result.authors:
            # arXiv author strings are "First Last" or "Last, First"
            authors.append(Author(name=a.name))

        # Determine primary category
        primary_cat = result.primary_category or ""
        categories = list(result.categories)

        # DOI (some arXiv papers cross-list with published versions)
        doi = result.doi or None

        return Paper(
            title=result.title.strip(),
            doi=doi,
            arxiv_id=result.entry_id.split("/")[-1],
            authors=authors,
            journal="arXiv preprint",
            journal_tier=JournalTier.PREPRINT,
            publication_date=result.published.date(),
            abstract=result.summary.strip() if result.summary else None,
            keywords=categories,
            language="en",
            source=PaperSource.ARXIV,
            source_url=result.entry_id,
            pdf_url=result.pdf_url,
            is_open_access=True,
        )
