"""Markdown briefing generator."""

import logging
from datetime import date
from pathlib import Path

from econ_brief.models.paper import Paper, JournalTier, AnalysisResult

logger = logging.getLogger(__name__)

# Chinese day-of-week names
_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# Dimension display names in Chinese
_DIMENSION_NAMES = {
    "research_topic": "研究主题 Research Topic",
    "methodology_data": "方法与数据 Methodology & Data",
    "variables": "变量与测度 Variables & Measurement",
    "mechanisms": "机制分析 Mechanism Analysis",
    "innovation": "创新点 Innovation",
    "theoretical_framework": "理论框架 Theoretical Framework",
    "empirical_strategy": "实证策略 Empirical Strategy",
    "key_findings": "主要发现 Key Findings",
    "robustness_highlights": "稳健性与拓展分析亮点 Robustness & Heterogeneity Highlights",
    "writing_approach": "写作特点 Writing Approach",
    "limitations": "局限性 Limitations",
    "extensions": "可扩展方向 Extensions",
    "china_relevance": "对中国研究的启示 China Relevance",
}


class MarkdownGenerator:
    """Generate a Markdown-format research briefing."""

    def __init__(self, output_dir: str | Path = "output/briefings"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        papers: list[Paper],
        summary: str,
        today: date | None = None,
        total_fetched: int = 0,
    ) -> str:
        """Generate a complete Markdown briefing.

        Args:
            papers: Analyzed papers sorted by relevance (already filtered/scored).
            summary: Executive summary text.
            today: Date of the briefing.
            total_fetched: Total papers originally fetched.

        Returns:
            Full Markdown string.
        """
        today = today or date.today()
        weekday = _WEEKDAYS[today.weekday()]

        # Group papers by tier
        groups = self._group_by_tier(papers)

        # Build sections
        sections: list[str] = []

        # Header
        sections.append(self._header(today, weekday, papers, total_fetched))

        # Executive summary
        sections.append(self._summary_section(summary))

        # Paper sections by tier
        sections.append("---\n")

        tier_order = [
            (JournalTier.CHINESE_TOP, "## 中文期刊 Chinese Journals"),
            (JournalTier.INTERNATIONAL_TOP5, "## 国际 Top 5 期刊 International Top 5"),
            (JournalTier.INTERNATIONAL_FIELD, "## 国际领域期刊 International Field Journals"),
            (JournalTier.PREPRINT, "## 工作论文与预印本 Working Papers & Preprints"),
        ]

        for tier, heading in tier_order:
            tier_papers = groups.get(tier, [])
            if tier_papers:
                sections.append(heading + "\n")
                for p in tier_papers:
                    sections.append(self._paper_card(p))
                sections.append("")

        # Footer
        sections.append(self._footer(today))

        return "\n".join(sections)

    def save(self, content: str, today: date | None = None) -> Path:
        """Save the briefing to a file."""
        today = today or date.today()
        filename = f"{today.isoformat()}.md"
        filepath = self.output_dir / filename
        filepath.write_text(content, encoding="utf-8")
        logger.info("Markdown briefing saved to %s", filepath)
        return filepath

    # ── Section builders ──────────────────────────────────────────

    def _header(
        self,
        today: date,
        weekday: str,
        papers: list[Paper],
        total_fetched: int,
    ) -> str:
        tier_counts: dict[str, int] = {}
        for p in papers:
            t = p.journal_tier.value if p.journal_tier else "other"
            tier_counts[t] = tier_counts.get(t, 0) + 1

        lines = [
            f"# 经济学每日科研简报 — {today.isoformat()} ({weekday})",
            "",
            "## 概览 Overview",
            "",
            f"- 📄 今日抓取论文: {total_fetched} 篇",
            f"- ⭐ 高相关论文 (≥6/10): {len(papers)} 篇",
        ]

        labels = {
            "intl_top5": "Top 5 期刊",
            "intl_field": "领域期刊",
            "preprint": "工作论文/预印本",
            "chinese_top": "中文期刊",
        }
        tier_parts = []
        for key, label in labels.items():
            count = tier_counts.get(key, 0)
            if count > 0:
                tier_parts.append(f"{label}: {count} 篇")
        lines.append(f"- 📊 来源分布: {' | '.join(tier_parts)}")
        lines.append("")
        lines.append("---")
        lines.append("")
        return "\n".join(lines)

    def _summary_section(self, summary: str) -> str:
        return f"## 今日摘要 Executive Summary\n\n{summary}\n"

    def _paper_card(self, p: Paper) -> str:
        """Render a single paper as a Markdown card."""
        score = p.relevance_score or 0
        score_emoji = "🟢" if score >= 8 else "🟡" if score >= 6 else "⚪"

        lines = [
            f"### {score_emoji} [{score:.1f}] {p.display_title}",
            "",
        ]

        # Metadata
        meta_parts = []
        if p.journal:
            meta_parts.append(f"**期刊:** {p.journal}")
        if p.publication_date:
            meta_parts.append(f"**日期:** {p.publication_date}")
        lines.append(" | ".join(meta_parts))
        lines.append("")

        if p.authors:
            lines.append(f"**作者:** {p.author_string}")
        if p.affiliation_string:
            lines.append(f"**机构:** {p.affiliation_string}")
        if p.analysis and p.analysis.affiliations_note:
            lines.append(f"**机构（补充）:** {p.analysis.affiliations_note}")
        if p.keywords:
            lines.append(f"**关键词:** {', '.join(p.keywords[:8])}")
        if p.topic_tags:
            lines.append(f"**主题标签:** {', '.join(p.topic_tags)}")
        lines.append(f"**新颖度:** {p.novelty_flag or 'N/A'}")

        if p.doi:
            lines.append(f"**DOI:** [{p.doi}](https://doi.org/{p.doi})")
        if p.source_url:
            lines.append(f"**链接:** [{p.source_url}]({p.source_url})")
        if p.pdf_url and p.is_open_access:
            lines.append(f"**PDF:** [{p.pdf_url}]({p.pdf_url})")

        lines.append("")

        # 10-dimension analysis
        if p.analysis:
            analysis_dict = p.analysis.to_dict()
            for key, label in _DIMENSION_NAMES.items():
                text = analysis_dict.get(key, "")
                if text:
                    lines.append(f"#### {label}")
                    lines.append("")
                    lines.append(text)
                    lines.append("")
        else:
            lines.append("*分析未完成 / Analysis not available*")
            lines.append("")

        lines.append("---")
        lines.append("")
        return "\n".join(lines)

    def _footer(self, today: date) -> str:
        return (
            "---\n\n"
            f"*Generated by [econ-brief](https://github.com) "
            f"v0.1.0 · 基于 Claude (Anthropic) 分析 · "
            f"{today.isoformat()}T08:17:00+08:00*\n"
        )

    @staticmethod
    def _group_by_tier(papers: list[Paper]) -> dict:
        """Group papers by their journal tier."""
        groups: dict = {}
        for p in papers:
            tier = p.journal_tier
            if tier not in groups:
                groups[tier] = []
            groups[tier].append(p)
        return groups
