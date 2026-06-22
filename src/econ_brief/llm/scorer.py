"""Stage 1: DeepSeek relevance scoring and filtering.

Uses deepseek-chat (V3) as the fast, cheap scoring model.
"""

import json
import logging

from econ_brief.llm.client import LLMClient
from econ_brief.llm.prompts import PromptManager
from econ_brief.models.paper import Paper

logger = logging.getLogger(__name__)

# DeepSeek Chat (V3) — fast and cheap for scoring
SCORER_MODEL = "deepseek-chat"
BATCH_SIZE = 5  # Papers per API call for scoring


class RelevanceScorer:
    """Score papers by relevance using DeepSeek Chat (Stage 1).

    This is the cheap filtering stage. Only papers scoring above the
    threshold proceed to Stage 2 deep analysis.
    """

    def __init__(
        self,
        client: LLMClient,
        prompts: PromptManager | None = None,
        model: str | None = None,
    ):
        self.client = client
        self.prompts = prompts or PromptManager()
        self.model = model or SCORER_MODEL

    def score_papers(self, papers: list[Paper]) -> list[Paper]:
        """Score papers in batches. Sets relevance_score on each paper."""
        if not papers:
            return papers

        for i in range(0, len(papers), BATCH_SIZE):
            batch = papers[i : i + BATCH_SIZE]
            try:
                self._score_batch(batch)
                logger.debug(
                    "Scored batch %d-%d of %d",
                    i,
                    min(i + BATCH_SIZE, len(papers)),
                    len(papers),
                )
            except Exception as e:
                logger.error("Scoring failed for batch %d: %s", i, e)
                for p in batch:
                    p.relevance_score = 5.0
                    p.topic_tags = []
                    p.novelty_flag = "low"
                    p.scoring_reasoning = f"Scoring error: {e}"

        logger.info(
            "Scoring complete: %d papers, avg score %.2f",
            len(papers),
            sum(p.relevance_score or 0 for p in papers) / max(len(papers), 1),
        )
        return papers

    def _score_batch(self, batch: list[Paper]) -> None:
        """Score a batch of papers in one API call."""
        papers_text = self._format_batch(batch)
        user_prompt = self.prompts.scorer_user.format(papers_text=papers_text)

        response_text = self.client.create_message(
            model=self.model,
            system_prompt=self.prompts.scorer_system,
            user_content=user_prompt,
            max_tokens=1024,
            temperature=0.3,
        )

        scores = self._parse_response(response_text)
        for item in scores.get("papers", []):
            idx = item.get("paper_index", -1)
            if 0 <= idx < len(batch):
                p = batch[idx]
                p.relevance_score = float(item.get("relevance_score", 5.0))
                p.topic_tags = item.get("topic_tags", [])
                p.novelty_flag = item.get("novelty_flag", "")
                p.scoring_reasoning = item.get("reasoning", "")

    @staticmethod
    def _format_batch(papers: list[Paper]) -> str:
        """Format a batch of papers for the scoring prompt."""
        lines: list[str] = []
        for idx, p in enumerate(papers):
            authors = p.author_string
            if len(authors) > 200:
                authors = authors[:197] + "..."

            abstract = p.abstract or "No abstract available"
            if len(abstract) > 800:
                abstract = abstract[:797] + "..."

            lines.append(
                f"[{idx}] Title: {p.title}\n"
                f"    Authors: {authors}\n"
                f"    Journal: {p.journal or 'Working Paper'}\n"
                f"    Date: {p.publication_date or 'N/A'}\n"
                f"    Abstract: {abstract}"
            )
        return "\n---\n".join(lines)

    @staticmethod
    def _parse_response(text: str) -> dict:
        """Parse the JSON response, handling markdown wrapping."""
        text = text.strip()

        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            import re
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            logger.warning("Could not parse scorer response as JSON")
            return {"papers": []}
