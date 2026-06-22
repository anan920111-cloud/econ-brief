"""State tracking for seen papers and run history."""

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class StateTracker:
    """Tracks pipeline state: seen papers, last run, run statistics.

    Uses a JSON file on disk, designed to be committed to the bot-data
    branch in GitHub Actions for persistence across workflow runs.
    """

    _DATA_DIR = Path("data")
    _SEEN_FILE = Path("data/seen_papers.json")
    _RUN_LOG_FILE = Path("data/run_log.json")

    def __init__(self):
        self._DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._seen: set[str] = set()
        self._run_log: list[dict] = []
        self._load()

    # ── Seen papers ───────────────────────────────────────────────

    @property
    def seen_count(self) -> int:
        return len(self._seen)

    def is_seen(self, key: str) -> bool:
        """Check if a paper key has been seen before."""
        return key in self._seen

    def mark_seen(self, keys: list[str]) -> None:
        """Mark paper keys as seen."""
        self._seen.update(keys)

    # ── Run log ───────────────────────────────────────────────────

    def record_run(
        self,
        papers_fetched: int,
        papers_new: int,
        papers_analyzed: int,
        tokens_used: int = 0,
        cost_estimate: float = 0.0,
        errors: list[str] | None = None,
    ) -> None:
        """Record a pipeline run."""
        self._run_log.append({
            "date": date.today().isoformat(),
            "timestamp": datetime.now().isoformat(),
            "papers_fetched": papers_fetched,
            "papers_new": papers_new,
            "papers_analyzed": papers_analyzed,
            "tokens_used": tokens_used,
            "cost_estimate": cost_estimate,
            "errors": errors or [],
        })
        # Keep only last 90 days
        if len(self._run_log) > 90:
            self._run_log = self._run_log[-90:]

    def last_run_date(self) -> Optional[date]:
        """Date of the most recent run."""
        if not self._run_log:
            return None
        return date.fromisoformat(self._run_log[-1]["date"])

    def run_stats(self) -> dict:
        """Summary statistics across all runs."""
        if not self._run_log:
            return {"total_runs": 0}
        total_cost = sum(r.get("cost_estimate", 0) for r in self._run_log)
        total_tokens = sum(r.get("tokens_used", 0) for r in self._run_log)
        return {
            "total_runs": len(self._run_log),
            "total_papers_analyzed": sum(r.get("papers_analyzed", 0) for r in self._run_log),
            "total_cost": round(total_cost, 4),
            "total_tokens": total_tokens,
            "first_run": self._run_log[0]["date"],
            "last_run": self._run_log[-1]["date"],
        }

    # ── Persistence ───────────────────────────────────────────────

    def save(self) -> None:
        """Persist all state to disk."""
        self._DATA_DIR.mkdir(parents=True, exist_ok=True)

        self._SEEN_FILE.write_text(
            json.dumps(sorted(self._seen), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self._RUN_LOG_FILE.write_text(
            json.dumps(self._run_log, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info(
            "State saved: %d seen papers, %d run records",
            len(self._seen),
            len(self._run_log),
        )

    def _load(self) -> None:
        """Load state from disk."""
        if self._SEEN_FILE.exists():
            try:
                data = json.loads(self._SEEN_FILE.read_text(encoding="utf-8"))
                self._seen = set(data)
                logger.debug("Loaded %d seen paper keys", len(self._seen))
            except (json.JSONDecodeError, OSError):
                self._seen = set()

        if self._RUN_LOG_FILE.exists():
            try:
                self._run_log = json.loads(self._RUN_LOG_FILE.read_text(encoding="utf-8"))
                logger.debug("Loaded %d run log entries", len(self._run_log))
            except (json.JSONDecodeError, OSError):
                self._run_log = []
