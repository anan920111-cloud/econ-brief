"""Unified data models for the econ-brief pipeline."""

from dataclasses import dataclass, field
from enum import Enum
from datetime import date
from typing import Optional


class PaperSource(Enum):
    """Origin of a paper in the pipeline."""

    OPENALEX = "openalex"
    ARXIV = "arxiv"
    NBER = "nber"
    RSS = "rss"
    CHINESE_JOURNAL = "chinese_journal"


class JournalTier(Enum):
    """Tier classification for journals."""

    INTERNATIONAL_TOP5 = "intl_top5"
    INTERNATIONAL_FIELD = "intl_field"
    CHINESE_TOP = "chinese_top"
    PREPRINT = "preprint"


@dataclass
class Author:
    """Author with optional affiliation and ORCID."""

    name: str
    affiliations: list[str] = field(default_factory=list)
    orcid: Optional[str] = None


@dataclass
class AnalysisResult:
    """Structured analysis of a paper."""

    research_topic: str = ""
    methodology_data: str = ""
    variables: str = ""  # Key variables and measurement methods
    innovation: str = ""
    theoretical_framework: str = ""
    empirical_strategy: str = ""
    key_findings: str = ""
    writing_approach: str = ""
    limitations: str = ""
    extensions: str = ""
    china_relevance: str = ""
    title_zh: str = ""  # Chinese translation of title (for EN papers)
    affiliations_note: str = ""  # Author institutions (if not in metadata)

    def to_dict(self) -> dict:
        return {
            "research_topic": self.research_topic,
            "methodology_data": self.methodology_data,
            "variables": self.variables,
            "innovation": self.innovation,
            "theoretical_framework": self.theoretical_framework,
            "empirical_strategy": self.empirical_strategy,
            "key_findings": self.key_findings,
            "writing_approach": self.writing_approach,
            "limitations": self.limitations,
            "extensions": self.extensions,
            "china_relevance": self.china_relevance,
            "title_zh": self.title_zh,
            "affiliations_note": self.affiliations_note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AnalysisResult":
        return cls(
            research_topic=d.get("research_topic", ""),
            methodology_data=d.get("methodology_data", ""),
            variables=d.get("variables", ""),
            innovation=d.get("innovation", ""),
            theoretical_framework=d.get("theoretical_framework", ""),
            empirical_strategy=d.get("empirical_strategy", ""),
            key_findings=d.get("key_findings", ""),
            writing_approach=d.get("writing_approach", ""),
            limitations=d.get("limitations", ""),
            extensions=d.get("extensions", ""),
            china_relevance=d.get("china_relevance", ""),
            title_zh=d.get("title_zh", ""),
            affiliations_note=d.get("affiliations_note", ""),
        )


@dataclass
class Paper:
    """Unified paper representation across all sources."""

    # Universal identifiers
    title: str
    title_en: Optional[str] = None  # English translation for Chinese papers
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    nber_id: Optional[str] = None
    openalex_id: Optional[str] = None

    # Bibliographic
    authors: list[Author] = field(default_factory=list)
    journal: Optional[str] = None
    journal_tier: Optional[JournalTier] = None
    publication_date: Optional[date] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None

    # Content
    abstract: Optional[str] = None
    abstract_zh: Optional[str] = None
    keywords: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    language: str = "en"

    # Source metadata
    source: PaperSource = PaperSource.OPENALEX
    source_url: Optional[str] = None
    is_open_access: bool = False
    pdf_url: Optional[str] = None

    # LLM analysis results
    relevance_score: Optional[float] = None
    topic_tags: list[str] = field(default_factory=list)
    novelty_flag: str = ""
    scoring_reasoning: str = ""
    analysis: Optional[AnalysisResult] = None

    # LLM-translated Chinese title (populated during Stage 2 for EN papers)
    title_zh: Optional[str] = None

    @property
    def display_title(self) -> str:
        """Best available title for display.

        Chinese papers: show Chinese title directly.
        English papers: show English title + Chinese translation if available.
        """
        if self.language == "zh":
            return self.title
        if self.title_zh:
            return f"{self.title}（{self.title_zh}）"
        return self.title

    @property
    def author_string(self) -> str:
        """Comma-separated author names."""
        return ", ".join(a.name for a in self.authors)

    @property
    def affiliation_string(self) -> str:
        """Unique affiliations across all authors."""
        affs: list[str] = []
        seen: set[str] = set()
        for a in self.authors:
            for aff in a.affiliations:
                if aff not in seen:
                    affs.append(aff)
                    seen.add(aff)
        return "; ".join(affs)

    @property
    def primary_key(self) -> str:
        """Canonical dedup key: DOI > arXiv ID > NBER ID > title hash."""
        import hashlib

        if self.doi:
            return self.doi.lower()
        if self.arxiv_id:
            return f"arxiv:{self.arxiv_id}"
        if self.nber_id:
            return f"nber:{self.nber_id}"
        return hashlib.sha256(
            self.title.strip().lower().encode()
        ).hexdigest()[:16]
