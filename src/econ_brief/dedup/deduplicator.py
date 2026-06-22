"""Three-pass deduplication strategy for paper pipeline."""

import hashlib
import json
import logging
from pathlib import Path

from thefuzz import fuzz

from econ_brief.models.paper import Paper

logger = logging.getLogger(__name__)


class Deduplicator:
    """Three-pass dedup: DOI exact → fuzzy title → seen database.

    Pass 1: Exact match on DOI (or arXiv ID, NBER ID)
    Pass 2: Fuzzy title match using token sort ratio (for papers without IDs)
    Pass 3: Check against persistent seen_papers.json database
    """

    def __init__(self, seen_file: str | Path = "data/seen_papers.json"):
        """
        Args:
            seen_file: Path to the seen papers JSON file.
        """
        self.seen_file = Path(seen_file)
        self._seen: set[str] = set()
        self._newly_seen: set[str] = set()
        self._load_seen()

    # ── Public API ────────────────────────────────────────────────

    def deduplicate(self, papers: list[Paper]) -> list[Paper]:
        """Run three-pass deduplication. Returns papers not seen before."""
        if not papers:
            return []

        # Pass 1: Exact identifier match within this batch
        papers = self._exact_dedup(papers)
        logger.debug("After exact dedup: %d papers", len(papers))

        # Pass 2: Fuzzy title match within this batch
        papers = self._fuzzy_dedup(papers)
        logger.debug("After fuzzy dedup: %d papers", len(papers))

        # Pass 3: Filter against persistent seen database
        new_papers = []
        for p in papers:
            key = self._paper_key(p)
            if key not in self._seen:
                new_papers.append(p)
                self._newly_seen.add(key)
            else:
                logger.debug("Already seen: %s", p.title[:80])

        logger.info(
            "Dedup: %d → %d new papers (filtered %d seen)",
            len(papers) + len(self._seen),
            len(new_papers),
            len(papers) - len(new_papers),
        )
        return new_papers

    def mark_seen(self, papers: list[Paper]) -> None:
        """Mark papers as seen (call after successful processing)."""
        for p in papers:
            self._seen.add(self._paper_key(p))

    def save(self) -> None:
        """Persist seen papers to disk."""
        self.seen_file.parent.mkdir(parents=True, exist_ok=True)
        sorted_keys = sorted(self._seen)
        self.seen_file.write_text(
            json.dumps(sorted_keys, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Saved %d seen paper keys to %s", len(sorted_keys), self.seen_file)

    # ── Private helpers ───────────────────────────────────────────

    def _load_seen(self) -> None:
        """Load previously seen paper keys from disk."""
        if self.seen_file.exists():
            try:
                data = json.loads(self.seen_file.read_text(encoding="utf-8"))
                self._seen = set(data)
                logger.info("Loaded %d seen paper keys", len(self._seen))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Could not load seen papers: %s", e)
                self._seen = set()

    @staticmethod
    def _exact_dedup(papers: list[Paper]) -> list[Paper]:
        """Deduplicate by exact identifier match (DOI, arXiv ID, NBER ID)."""
        seen_ids: set[str] = set()
        result: list[Paper] = []
        for p in papers:
            dedup_id = Deduplicator._dedup_id(p)
            if dedup_id and dedup_id in seen_ids:
                continue
            if dedup_id:
                seen_ids.add(dedup_id)
            result.append(p)
        return result

    @staticmethod
    def _fuzzy_dedup(papers: list[Paper]) -> list[Paper]:
        """Deduplicate by fuzzy title matching (for papers without IDs)."""
        result: list[Paper] = []
        seen_titles: list[str] = []
        for p in papers:
            is_dup = False
            norm_title = Deduplicator._normalize_title(p.title)
            for existing in seen_titles:
                if fuzz.token_sort_ratio(norm_title, existing) > 90:
                    is_dup = True
                    logger.debug("Fuzzy dup: '%s' ~ '%s'", p.title[:60], existing[:60])
                    break
            if not is_dup:
                seen_titles.append(norm_title)
                result.append(p)
        return result

    @staticmethod
    def _paper_key(p: Paper) -> str:
        """Canonical dedup key for persistent storage."""
        dedup_id = Deduplicator._dedup_id(p)
        if dedup_id:
            return dedup_id
        # Fall back to title hash
        title_hash = hashlib.sha256(
            Deduplicator._normalize_title(p.title).encode()
        ).hexdigest()[:16]
        return f"title:{title_hash}"

    @staticmethod
    def _dedup_id(p: Paper) -> str | None:
        """Return the best identifier for exact dedup."""
        if p.doi:
            return f"doi:{p.doi.lower()}"
        if p.arxiv_id:
            return f"arxiv:{p.arxiv_id}"
        if p.nber_id:
            return f"nber:{p.nber_id}"
        return None

    @staticmethod
    def _normalize_title(title: str) -> str:
        """Normalize a title for comparison: lowercase, strip punctuation."""
        return title.strip().lower()
