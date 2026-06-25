"""Stage 2: DeepSeek deep 10-dimension analysis.

Uses deepseek-chat (V3) or deepseek-reasoner (R1) for detailed analysis.
"""

import json
import logging

from econ_brief.llm.client import LLMClient
from econ_brief.llm.prompts import PromptManager
from econ_brief.models.paper import AnalysisResult, Paper

logger = logging.getLogger(__name__)

# DeepSeek Chat (V3) — strong general reasoning, very cheap
ANALYZER_MODEL = "deepseek-chat"


class DeepAnalyzer:
    """Deep paper analysis using DeepSeek (Stage 2).

    Analyzes each paper across 10 structured dimensions in Chinese
    with English technical terms preserved.
    """

    def __init__(
        self,
        client: LLMClient,
        prompts: PromptManager | None = None,
        model: str | None = None,
    ):
        self.client = client
        self.prompts = prompts or PromptManager()
        self.model = model or ANALYZER_MODEL

    def analyze_papers(self, papers: list[Paper]) -> list[Paper]:
        """Analyze papers one at a time for depth.

        Returns papers with analysis field populated.
        """
        if not papers:
            return papers

        for i, paper in enumerate(papers):
            try:
                self._analyze_one(paper, i)
                logger.debug(
                    "Analyzed paper %d/%d: %s",
                    i + 1,
                    len(papers),
                    paper.title[:60],
                )
            except Exception as e:
                logger.error(
                    "Analysis failed for paper %d '%s': %s",
                    i,
                    paper.title[:60],
                    e,
                )
                paper.analysis = AnalysisResult(
                    research_topic=f"分析失败: {e}",
                )

        logger.info(
            "Analysis complete: %d papers analyzed",
            len([p for p in papers if p.analysis is not None]),
        )
        return papers

    def write_summary(
        self,
        papers: list[Paper],
        today_str: str,
        total_fetched: int,
    ) -> str:
        """Write an executive summary of today's briefing."""
        if not papers:
            return "今日无高相关度论文。"

        tier_counts: dict[str, int] = {}
        for p in papers:
            tier_name = p.journal_tier.value if p.journal_tier else "other"
            tier_counts[tier_name] = tier_counts.get(tier_name, 0) + 1
        tier_summary = ", ".join(f"{k}: {v}篇" for k, v in tier_counts.items())

        top_papers_text = ""
        for i, p in enumerate(papers[:5]):
            top_papers_text += (
                f"{i + 1}. [{p.relevance_score or '?'}/10] {p.title}\n"
                f"   {p.author_string}\n"
                f"   {p.journal or 'Working Paper'}\n"
                f"   {p.abstract[:200] if p.abstract else '无摘要'}...\n\n"
            )

        user_prompt = self.prompts.summary_user.format(
            date=today_str,
            total_papers=len(papers),
            tier_summary=tier_summary,
            top_papers_summary=top_papers_text,
        )

        try:
            return self.client.create_message(
                model=self.model,
                system_prompt=self.prompts.summary_system,
                user_content=user_prompt,
                max_tokens=1024,
                temperature=0.3,
            )
        except Exception as e:
            logger.error("Summary generation failed: %s", e)
            return f"今日共分析 {len(papers)} 篇论文，涵盖 {tier_summary}。"

    # ── Private helpers ───────────────────────────────────────────

    def _analyze_one(self, paper: Paper, index: int) -> None:
        """Analyze a single paper."""
        user_prompt = self.prompts.analyzer_user.format(
            title=paper.title,
            authors=paper.author_string,
            affiliations=paper.affiliation_string or "N/A",
            journal=paper.journal or "Working Paper / Preprint",
            date=str(paper.publication_date) if paper.publication_date else "N/A",
            keywords=", ".join(paper.keywords) if paper.keywords else "N/A",
            abstract=paper.abstract or "No abstract available",
        )

        response_text = self.client.create_message(
            model=self.model,
            system_prompt=self.prompts.analyzer_system,
            user_content=user_prompt,
            max_tokens=4096,
            temperature=0.3,
        )

        result = self._parse_response(response_text, index)
        paper.analysis = AnalysisResult.from_dict(
            result.get("analysis", {})
        )
        # Copy title_zh back to paper for display
        if paper.analysis.title_zh:
            paper.title_zh = paper.analysis.title_zh

    @staticmethod
    def _parse_response(text: str, paper_index: int) -> dict:
        """Parse JSON response, handling markdown code fences."""
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
            logger.warning(
                "Could not parse analyzer response for paper %d as JSON",
                paper_index,
            )
            return {"paper_index": paper_index, "analysis": {}}
