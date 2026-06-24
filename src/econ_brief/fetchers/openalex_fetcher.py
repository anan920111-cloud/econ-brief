"""OpenAlex API fetcher — primary source for published journal articles."""

import asyncio
import logging
from datetime import date, timedelta
from typing import Optional

from pyalex import Works, config as pyalex_config

from econ_brief.fetchers.base import AbstractFetcher
from econ_brief.models.paper import Author, Paper, PaperSource, JournalTier

logger = logging.getLogger(__name__)

# Map tier strings to JournalTier enum
_TIER_MAP = {
    "intl_top5": JournalTier.INTERNATIONAL_TOP5,
    "intl_field": JournalTier.INTERNATIONAL_FIELD,
    "chinese_top": JournalTier.CHINESE_TOP,
    None: None,
}


class OpenAlexFetcher(AbstractFetcher):
    """Fetch papers from OpenAlex by journal ISSN."""

    def __init__(self, journals: list[dict], email: str | None = None):
        """
        Args:
            journals: List of dicts with keys: issn, name, tier, name_en (optional).
            email: Email for OpenAlex polite pool (higher rate limits).
        """
        self.journals = journals
        if email:
            pyalex_config.email = email
        pyalex_config.max_retries = 3

    def source_name(self) -> str:
        return "OpenAlex"

    async def fetch(self, lookback_days: int = 3) -> list[Paper]:
        since = self._cutoff_date(lookback_days)
        all_papers: list[Paper] = []

        for journal_info in self.journals:
            issn = journal_info["issn"]
            try:
                papers = await self._fetch_journal(issn, journal_info, since)
                all_papers.extend(papers)
                if papers:
                    logger.debug(
                        "OpenAlex: %d papers from %s (%s)",
                        len(papers),
                        journal_info.get("name", issn),
                        issn,
                    )
            except Exception as e:
                logger.warning(
                    "OpenAlex fetch failed for %s (%s): %s",
                    journal_info.get("name", issn),
                    issn,
                    e,
                )
            # Rate limiting: be gentle with the API
            await asyncio.sleep(0.1)

        logger.info("OpenAlex: %d total papers across %d journals", len(all_papers), len(self.journals))
        return all_papers

    async def _fetch_journal(
        self, issn: str, journal_info: dict, since: date
    ) -> list[Paper]:
        """Fetch papers for a single journal, by source_id or ISSN.

        Chinese journals are looked up by OpenAlex source ID (more reliable
        than ISSN matching in OpenAlex). International journals use ISSN.
        """
        papers: list[Paper] = []
        tier = _TIER_MAP.get(journal_info.get("tier"))

        # Chinese journals: prefer source_id lookup
        source_id = journal_info.get("openalex_source_id")
        if source_id:
            source_filter = {
                "primary_location": {
                    "source": {"id": f"https://openalex.org/{source_id}"}
                }
            }
        else:
            source_filter = {
                "primary_location": {"source": {"issn": issn}}
            }

        try:
            results = (
                Works()
                .filter(
                    **source_filter,
                    from_publication_date=str(since),
                )
                .sort(publication_date="desc")
                .paginate(per_page=25)
            )

            for page in results:
                for work in page:
                    paper = self._work_to_paper(work, journal_info, tier)
                    if paper:
                        papers.append(paper)
        except Exception:
            raise

        return papers

    def _work_to_paper(
        self, work: dict, journal_info: dict, tier: JournalTier | None
    ) -> Paper | None:
        """Map an OpenAlex Work object to our unified Paper model."""
        try:
            # Title
            title = work.get("title")
            if not title:
                return None

            # Authors
            authors: list[Author] = []
            for authorship in work.get("authorships", []):
                author_data = authorship.get("author", {})
                name = author_data.get("display_name", "")
                orcid = author_data.get("orcid")

                # Affiliations
                affiliations: list[str] = []
                for inst in authorship.get("institutions", []):
                    inst_name = inst.get("display_name", "")
                    if inst_name:
                        affiliations.append(inst_name)

                if name:
                    authors.append(
                        Author(
                            name=name,
                            affiliations=affiliations,
                            orcid=orcid,
                        )
                    )

            # Abstract
            abstract = None
            if work.get("abstract_inverted_index"):
                abstract = self._reconstruct_abstract(
                    work["abstract_inverted_index"]
                )

            # Concepts / keywords
            concepts: list[str] = []
            for concept in work.get("concepts", []):
                cname = concept.get("display_name", "")
                if cname:
                    concepts.append(cname)

            keywords: list[str] = []
            for kw in work.get("keywords", []):
                kname = kw.get("display_name", "")
                if kname:
                    keywords.append(kname)

            # Publication date
            pub_date_str = work.get("publication_date")
            pub_date = None
            if pub_date_str:
                try:
                    pub_date = date.fromisoformat(pub_date_str)
                except (ValueError, TypeError):
                    pass

            # DOI
            doi = work.get("doi")
            if doi:
                # Remove URL prefix if present
                doi = doi.replace("https://doi.org/", "")

            # OA status
            oa = work.get("open_access", {})
            is_oa = oa.get("is_oa", False)
            pdf_url = oa.get("oa_url") if is_oa else None

            # Primary location / source URL
            primary_loc = work.get("primary_location", {})
            landing_page = primary_loc.get("landing_page_url")

            # Use English title if journal is Chinese
            title_en = None
            language = "en"
            if journal_info.get("tier") == "chinese_top":
                title_en = journal_info.get("name_en")
                language = "zh"

            return Paper(
                title=title,
                title_en=title_en,
                doi=doi,
                openalex_id=work.get("id"),
                authors=authors,
                journal=journal_info.get("name"),
                journal_tier=tier,
                publication_date=pub_date,
                abstract=abstract,
                keywords=keywords,
                concepts=concepts,
                language=language,
                source=PaperSource.OPENALEX,
                source_url=landing_page,
                is_open_access=is_oa,
                pdf_url=pdf_url,
            )
        except Exception as e:
            logger.debug("Failed to map OpenAlex work: %s", e)
            return None

    @staticmethod
    def _reconstruct_abstract(inverted_index: dict) -> str:
        """Reconstruct abstract text from OpenAlex inverted index format."""
        if not inverted_index:
            return ""
        # Build position -> word mapping
        max_pos = 0
        for positions in inverted_index.values():
            for pos in positions:
                if pos > max_pos:
                    max_pos = pos
        words = [""] * (max_pos + 1)
        for word, positions in inverted_index.items():
            for pos in positions:
                words[pos] = word
        return " ".join(words)
