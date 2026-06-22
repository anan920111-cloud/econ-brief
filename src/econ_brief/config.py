"""Configuration loader for econ-brief."""

import logging
import os
from pathlib import Path
from typing import Optional

import yaml

from econ_brief.constants import (
    INTL_TOP5,
    INTL_FIELD,
    CHINESE_JOURNALS,
    ARXIV_CATEGORIES,
)
from econ_brief.llm.prompts import PromptManager

logger = logging.getLogger(__name__)


class Config:
    """Central configuration aggregating YAML files and environment variables."""

    def __init__(
        self,
        journals_path: str | Path | None = None,
        prompts_path: str | Path | None = None,
    ):
        # Default paths
        if journals_path is None:
            journals_path = Path("config/journals.yaml")
        if prompts_path is None:
            prompts_path = Path("config/prompts.yaml")

        # Load journal config (from YAML or built-in constants)
        self.intl_top5, self.intl_field, self.chinese_journals = self._load_journals(
            journals_path
        )

        # All international journals combined
        self.intl_journals = self.intl_top5 + self.intl_field

        # ArXiv categories
        self.arxiv_categories = ARXIV_CATEGORIES

        # Prompts
        self.prompts = PromptManager(prompts_path)

        # Fetch settings
        self.lookback_days = int(os.environ.get("LOOKBACK_DAYS", "3"))
        self.openalex_email = os.environ.get("OPENALEX_EMAIL")

        # LLM settings
        self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self.haiku_model = "claude-haiku-4-5-20250514"
        self.sonnet_model = "claude-sonnet-4-20250514"

        # Relevance filter
        self.min_relevance_score = float(
            os.environ.get("MIN_RELEVANCE_SCORE", "6.0")
        )
        self.max_stage2_papers = int(
            os.environ.get("MAX_STAGE2_PAPERS", "30")
        )

        # Email settings
        self.email_config = {
            "host": os.environ.get("SMTP_HOST", ""),
            "port": int(os.environ.get("SMTP_PORT", "587")),
            "username": os.environ.get("SMTP_USERNAME", ""),
            "password": os.environ.get("SMTP_PASSWORD", ""),
            "from_addr": os.environ.get("EMAIL_FROM", ""),
            "to_addrs": os.environ.get("EMAIL_TO", ""),
        }

    @property
    def email_configured(self) -> bool:
        """Check if email settings are present."""
        ec = self.email_config
        return bool(ec["host"] and ec["username"] and ec["password"] and ec["to_addrs"])

    # ── Private helpers ───────────────────────────────────────────

    def _load_journals(
        self, path: str | Path
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """Load journal configs, falling back to built-in constants."""
        path = Path(path)

        if not path.exists():
            logger.info("Journal config not found at %s, using built-in defaults", path)
            return INTL_TOP5, INTL_FIELD, CHINESE_JOURNALS

        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            intl_top5 = data.get("international_top5", INTL_TOP5)
            intl_field = data.get("international_field", INTL_FIELD)
            chinese = data.get("chinese_journals", CHINESE_JOURNALS)

            # Ensure tier field is set
            for j in intl_top5:
                j.setdefault("tier", "intl_top5")
            for j in intl_field:
                j.setdefault("tier", "intl_field")
            for j in chinese:
                j.setdefault("tier", "chinese_top")

            logger.info(
                "Loaded %d international top5, %d international field, %d Chinese journals from %s",
                len(intl_top5),
                len(intl_field),
                len(chinese),
                path,
            )
            return intl_top5, intl_field, chinese

        except Exception as e:
            logger.warning("Error loading journal config: %s. Using built-in defaults.", e)
            return INTL_TOP5, INTL_FIELD, CHINESE_JOURNALS


def load_config(
    journals_path: str | Path | None = None,
    prompts_path: str | Path | None = None,
) -> Config:
    """Create a Config instance from files and environment."""
    return Config(journals_path=journals_path, prompts_path=prompts_path)
