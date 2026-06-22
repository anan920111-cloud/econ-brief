"""Tests for the deduplication module."""

import json
import tempfile
from pathlib import Path

from econ_brief.dedup.deduplicator import Deduplicator
from econ_brief.models.paper import Author, Paper, PaperSource


def _make_paper(title: str, doi: str | None = None) -> Paper:
    return Paper(
        title=title,
        doi=doi,
        authors=[Author(name="Test Author")],
        source=PaperSource.OPENALEX,
    )


def test_exact_doi_dedup():
    """Papers with the same DOI should be deduplicated."""
    p1 = _make_paper("Paper One", doi="10.1234/abcd")
    p2 = _make_paper("Paper One (Duplicate)", doi="10.1234/ABCD")  # case diff

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        f.write(b"[]")
        seen_path = f.name

    dedup = Deduplicator(seen_path)
    result = dedup.deduplicate([p1, p2])
    assert len(result) == 1

    Path(seen_path).unlink(missing_ok=True)


def test_fuzzy_title_dedup():
    """Papers with very similar titles should be detected as duplicates."""
    p1 = _make_paper("The Effect of Minimum Wage on Employment")
    p2 = _make_paper("Effect of Minimum Wage on Employment The")

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        f.write(b"[]")
        seen_path = f.name

    dedup = Deduplicator(seen_path)
    result = dedup.deduplicate([p1, p2])
    assert len(result) == 1

    Path(seen_path).unlink(missing_ok=True)


def test_different_papers_not_deduped():
    """Different papers should not be deduplicated."""
    p1 = _make_paper("The Effect of Minimum Wage on Employment")
    p2 = _make_paper("Monetary Policy and Inflation Expectations")

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        f.write(b"[]")
        seen_path = f.name

    dedup = Deduplicator(seen_path)
    result = dedup.deduplicate([p1, p2])
    assert len(result) == 2

    Path(seen_path).unlink(missing_ok=True)


def test_seen_papers_persist():
    """Previously seen papers should be excluded on next run."""
    p1 = _make_paper("Paper One", doi="10.1234/abcd")
    p2 = _make_paper("Paper Two", doi="10.1234/efgh")

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        f.write(b"[]")
        seen_path = f.name

    # First run: both are new
    dedup1 = Deduplicator(seen_path)
    result1 = dedup1.deduplicate([p1, p2])
    assert len(result1) == 2
    dedup1.mark_seen(result1)
    dedup1.save()

    # Second run: p1 appears again (should be filtered)
    dedup2 = Deduplicator(seen_path)
    result2 = dedup2.deduplicate([p1])
    assert len(result2) == 0

    Path(seen_path).unlink(missing_ok=True)


def test_empty_papers():
    """Empty list should return empty."""
    dedup = Deduplicator()
    result = dedup.deduplicate([])
    assert result == []
