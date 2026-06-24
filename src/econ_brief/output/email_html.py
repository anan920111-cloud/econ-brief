"""HTML email generator for the research briefing."""

import logging
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from econ_brief.models.paper import Paper, JournalTier

logger = logging.getLogger(__name__)

# Dimension display names
_DIMENSION_NAMES = {
    "research_topic": "研究主题 Research Topic",
    "methodology_data": "方法与数据 Methodology & Data",
    "innovation": "创新点 Innovation",
    "theoretical_framework": "理论框架 Theoretical Framework",
    "empirical_strategy": "实证策略 Empirical Strategy",
    "key_findings": "主要发现 Key Findings",
    "writing_approach": "写作特点 Writing Approach",
    "limitations": "局限性 Limitations",
    "extensions": "可扩展方向 Extensions",
    "china_relevance": "对中国研究的启示 China Relevance",
}

_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


class EmailHTMLGenerator:
    """Generate HTML email from analyzed papers."""

    def __init__(self, template_dir: str | Path | None = None):
        if template_dir:
            template_dir = Path(template_dir)
        else:
            template_dir = Path(__file__).parent / "templates"

        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)) if template_dir.exists() else None,
            autoescape=select_autoescape(["html", "xml"]),
        )

    def generate(
        self,
        papers: list[Paper],
        summary: str,
        today: date | None = None,
        total_fetched: int = 0,
    ) -> str:
        """Generate a complete HTML email.

        Args:
            papers: Analyzed papers sorted by relevance.
            summary: Executive summary text.
            today: Date of the briefing.
            total_fetched: Total papers originally fetched.

        Returns:
            Full HTML string.
        """
        today = today or date.today()
        weekday = _WEEKDAYS[today.weekday()]

        # Group papers by tier
        groups = self._group_by_tier(papers)

        # Try template first, fall back to inline HTML
        try:
            template = self.env.get_template("email_base.html")
            return template.render(
                date=today.isoformat(),
                weekday=weekday,
                total_fetched=total_fetched,
                analyzed_count=len(papers),
                summary=summary,
                groups=groups,
                tier_labels={
                    JournalTier.CHINESE_TOP: "中文期刊",
                    JournalTier.INTERNATIONAL_TOP5: "国际 Top 5 期刊",
                    JournalTier.INTERNATIONAL_FIELD: "国际领域期刊",
                    JournalTier.PREPRINT: "工作论文与预印本",
                },
            )
        except Exception as e:
            logger.debug("Template not found, using inline HTML: %s", e)
            return self._inline_html(papers, summary, today, weekday, total_fetched)

    def _inline_html(
        self,
        papers: list[Paper],
        summary: str,
        today: date,
        weekday: str,
        total_fetched: int,
    ) -> str:
        """Generate HTML inline (no template dependency)."""

        def paper_html(p: Paper) -> str:
            score = p.relevance_score or 0
            badge_color = "#22c55e" if score >= 8 else "#eab308" if score >= 6 else "#9ca3af"

            # Build analysis sections
            analysis_html = ""
            if p.analysis:
                ad = p.analysis.to_dict()
                for key, label in _DIMENSION_NAMES.items():
                    text = ad.get(key, "")
                    if text:
                        # Convert newlines to <br> and escape HTML
                        text_escaped = (
                            text.replace("&", "&amp;")
                            .replace("<", "&lt;")
                            .replace(">", "&gt;")
                            .replace("\n", "<br>")
                        )
                        analysis_html += f"""
                        <div style="margin: 8px 0;">
                          <strong style="color: #374151;">{label}</strong>
                          <p style="margin: 4px 0 8px 0; color: #4b5563; line-height: 1.6;">
                            {text_escaped}
                          </p>
                        </div>"""

            authors_str = p.author_string[:300]
            affiliations = p.affiliation_string[:300]

            return f"""
            <div style="border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin: 12px 0; background: #fff;">
              <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                <span style="background: {badge_color}; color: white; padding: 2px 10px; border-radius: 12px; font-size: 13px; font-weight: 600;">
                  {score:.1f}
                </span>
                <h3 style="margin: 0; font-size: 16px; color: #111827;">
                  {p.display_title}
                </h3>
              </div>
              <div style="color: #6b7280; font-size: 13px; margin-bottom: 8px;">
                {f'<strong>{p.journal}</strong> · ' if p.journal else ''}{p.publication_date or ''}
              </div>
              <div style="color: #374151; font-size: 14px; margin-bottom: 4px;">
                <strong>作者:</strong> {authors_str}
              </div>
              {f'<div style="color: #374151; font-size: 14px; margin-bottom: 8px;"><strong>机构:</strong> {affiliations}</div>' if affiliations else ''}
              {analysis_html}
              {f'<div style="margin-top: 8px;"><a href="https://doi.org/{p.doi}" style="color: #3b82f6; font-size: 13px;">DOI: {p.doi}</a></div>' if p.doi else ''}
            </div>"""

        # Group papers by tier
        groups = self._group_by_tier(papers)
        tier_order = [
            (JournalTier.CHINESE_TOP, "🇨🇳 中文期刊"),
            (JournalTier.INTERNATIONAL_TOP5, "🌍 国际 Top 5 期刊"),
            (JournalTier.INTERNATIONAL_FIELD, "📚 国际领域期刊"),
            (JournalTier.PREPRINT, "📝 工作论文与预印本"),
        ]

        papers_sections = ""
        for tier, heading in tier_order:
            tier_papers = groups.get(tier, [])
            if tier_papers:
                papers_sections += f'<h2 style="color: #1f2937; border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; margin-top: 24px;">{heading} ({len(tier_papers)}篇)</h2>'
                for p in tier_papers:
                    papers_sections += paper_html(p)

        tier_counts = ", ".join(
            f"{tier.value}: {len(groups.get(tier, []))}篇"
            for tier in tier_order
            if groups.get(tier)
        )

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>经济学每日简报 — {today.isoformat()}</title>
</head>
<body style="margin: 0; padding: 0; background: #f9fafb; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Noto Sans SC', sans-serif;">
<div style="max-width: 680px; margin: 0 auto; padding: 20px;">

  <!-- Header -->
  <div style="background: linear-gradient(135deg, #1e40af, #3b82f6); color: white; padding: 24px; border-radius: 12px; margin-bottom: 20px;">
    <h1 style="margin: 0 0 4px 0; font-size: 22px;">📊 经济学每日科研简报</h1>
    <div style="font-size: 14px; opacity: 0.9;">{today.isoformat()} {weekday} · Econ Research Brief</div>
  </div>

  <!-- Stats bar -->
  <div style="display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap;">
    <div style="flex: 1; min-width: 100px; background: white; border-radius: 8px; padding: 12px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.08);">
      <div style="font-size: 24px; font-weight: 700; color: #1e40af;">{total_fetched}</div>
      <div style="font-size: 12px; color: #6b7280;">抓取论文</div>
    </div>
    <div style="flex: 1; min-width: 100px; background: white; border-radius: 8px; padding: 12px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.08);">
      <div style="font-size: 24px; font-weight: 700; color: #059669;">{len(papers)}</div>
      <div style="font-size: 12px; color: #6b7280;">高相关分析</div>
    </div>
  </div>

  <!-- Executive Summary -->
  <div style="background: white; border-radius: 8px; padding: 16px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08);">
    <h2 style="color: #1f2937; margin-top: 0; font-size: 18px;">📋 今日摘要</h2>
    <div style="color: #374151; line-height: 1.7; font-size: 14px;">
      {summary.replace(chr(10), '<br>')}
    </div>
  </div>

  <!-- Papers -->
  {papers_sections}

  <!-- Footer -->
  <div style="text-align: center; color: #9ca3af; font-size: 12px; margin-top: 32px; padding: 16px; border-top: 1px solid #e5e7eb;">
    Generated by econ-brief v0.1.0 · 基于 Claude (Anthropic) 分析<br>
    Unsubscribe or manage settings in the GitHub repository.
  </div>

</div>
</body>
</html>"""

    @staticmethod
    def _group_by_tier(papers: list[Paper]) -> dict:
        groups: dict = {}
        for p in papers:
            tier = p.journal_tier
            if tier not in groups:
                groups[tier] = []
            groups[tier].append(p)
        return groups
