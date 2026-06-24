"""Main entry point for the econ-brief pipeline.

Usage:
    econ-brief                    # Run the full pipeline
    econ-brief --fetch-only       # Only fetch papers, skip LLM
    econ-brief --no-email         # Skip email delivery
    econ-brief --dry-run          # Fetch but don't analyze or email
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import date

from econ_brief.config import load_config
from econ_brief.dedup import Deduplicator
from econ_brief.fetchers import fetch_all
from econ_brief.llm import LLMClient, RelevanceScorer, DeepAnalyzer
from econ_brief.output import MarkdownGenerator, EmailHTMLGenerator, EmailSender
from econ_brief.state import StateTracker

# ── Logging setup ──────────────────────────────────────────────────


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("arxiv").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


# ── Pipeline steps ─────────────────────────────────────────────────


async def run_pipeline(
    config,
    fetch_only: bool = False,
    no_email: bool = False,
    dry_run: bool = False,
) -> int:
    """Run the complete econ-brief pipeline. Returns exit code."""
    today = date.today()
    errors: list[str] = []
    logger = logging.getLogger("pipeline")

    # ── 0. Validate configuration ──────────────────────────────────
    if not dry_run and not fetch_only:
        if not config.deepseek_api_key:
            logger.error("DEEPSEEK_API_KEY environment variable is required")
            return 1

    # ── 1. Fetch papers from all sources ───────────────────────────
    logger.info("=" * 60)
    logger.info("PHASE 1: Fetching papers from all sources")
    logger.info("=" * 60)

    all_papers = await fetch_all(
        intl_journals=config.intl_journals,
        chinese_journals=config.chinese_journals,
        lookback_days=config.lookback_days,
        lookback_days_zh=config.lookback_days_zh,
        email=config.openalex_email,
    )

    total_fetched = len(all_papers)
    logger.info("Total fetched: %d papers", total_fetched)

    if not all_papers:
        logger.info("No papers fetched. Exiting.")
        return 0

    if fetch_only or dry_run:
        for p in all_papers[:20]:
            print(f"  [{p.source.value}] {p.title[:100]}")
        if len(all_papers) > 20:
            print(f"  ... and {len(all_papers) - 20} more")
        return 0

    # ── 2. Deduplicate ─────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("PHASE 2: Deduplication")
    logger.info("=" * 60)

    dedup = Deduplicator()
    new_papers = dedup.deduplicate(all_papers)
    logger.info("New papers after dedup: %d", len(new_papers))

    if not new_papers:
        logger.info("No new papers after dedup. Exiting.")
        return 0

    # ── 3. Stage 1: Relevance scoring (deepseek-chat) ──────────────
    logger.info("=" * 60)
    logger.info("PHASE 3: Stage 1 — Relevance scoring (DeepSeek)")
    logger.info("=" * 60)

    client = LLMClient(
        api_key=config.deepseek_api_key,
        base_url=config.deepseek_base_url,
    )
    scorer = RelevanceScorer(
        client=client,
        prompts=config.prompts,
        model=config.scorer_model,
    )
    scored_papers = scorer.score_papers(new_papers)

    # Filter by relevance — separate thresholds for EN and ZH
    # DeepSeek scores Chinese papers lower on average, so we use a lower
    # cutoff for zh papers to avoid unfairly filtering them out.
    # Also enforce a minimum Chinese paper quota that survives the cap.
    en_qualified: list = []
    zh_qualified: list = []
    zh_rest: list = []  # zh papers below threshold (for quota fill)
    for p in scored_papers:
        if p.language == "zh":
            if (p.relevance_score or 0) >= config.min_relevance_score_zh:
                zh_qualified.append(p)
            else:
                zh_rest.append(p)
        else:
            if (p.relevance_score or 0) >= config.min_relevance_score:
                en_qualified.append(p)

    # Sort within each group
    en_qualified.sort(key=lambda p: p.relevance_score or 0, reverse=True)
    zh_qualified.sort(key=lambda p: p.relevance_score or 0, reverse=True)
    zh_rest.sort(key=lambda p: p.relevance_score or 0, reverse=True)

    # Fill Chinese quota from below-threshold papers if needed
    zh_selected = list(zh_qualified)
    zh_quota_fill = 0
    while len(zh_selected) < config.min_chinese_stage2 and zh_rest:
        zh_selected.append(zh_rest.pop(0))
        zh_quota_fill += 1
    if zh_quota_fill > 0:
        logger.info(
            "Chinese quota: added %d extra zh papers (below threshold) "
            "to meet minimum of %d",
            zh_quota_fill,
            config.min_chinese_stage2,
        )

    # Build final list: EN papers capped at max_english_stage2
    en_selected = en_qualified[: config.max_english_stage2]

    # Also respect overall cap
    total_limit = min(
        config.max_stage2_papers,
        len(zh_selected) + config.max_english_stage2,
    )
    if len(zh_selected) + len(en_selected) > total_limit:
        en_selected = en_selected[: max(0, total_limit - len(zh_selected))]

    top_papers = en_selected + zh_selected
    top_papers.sort(key=lambda p: p.relevance_score or 0, reverse=True)

    logger.info(
        "Papers selected (EN≥%.1f ZH≥%.1f min_zh=%d max_en=%d): "
        "%d total (EN=%d ZH=%d quota_fill=%d)",
        config.min_relevance_score,
        config.min_relevance_score_zh,
        config.min_chinese_stage2,
        config.max_english_stage2,
        len(top_papers),
        len(en_selected),
        len(zh_selected),
        zh_quota_fill,
    )

    if not top_papers:
        logger.info("No papers above relevance threshold. Exiting.")
        dedup.mark_seen(new_papers)
        dedup.save()
        return 0

    # ── 4. Stage 2: Deep analysis (deepseek-chat) ──────────────────
    logger.info("=" * 60)
    logger.info("PHASE 4: Stage 2 — Deep analysis (DeepSeek)")
    logger.info("=" * 60)

    analyzer = DeepAnalyzer(
        client=client,
        prompts=config.prompts,
        model=config.analyzer_model,
    )
    analyzed_papers = analyzer.analyze_papers(top_papers)

    # Generate executive summary
    summary = analyzer.write_summary(
        analyzed_papers,
        today.isoformat(),
        total_fetched,
    )

    # ── 5. Generate outputs ────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("PHASE 5: Generating outputs")
    logger.info("=" * 60)

    md_gen = MarkdownGenerator()
    md_content = md_gen.generate(
        analyzed_papers, summary, today, total_fetched
    )
    md_path = md_gen.save(md_content, today)
    logger.info("Markdown briefing: %s", md_path)

    html_gen = EmailHTMLGenerator()
    html_content = html_gen.generate(
        analyzed_papers, summary, today, total_fetched
    )

    # ── 6. Deliver ─────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("PHASE 6: Delivery")
    logger.info("=" * 60)

    email_sent = False
    if not no_email and config.email_configured:
        sender = EmailSender(config.email_config)
        email_sent = sender.send(html_content, today)
        if email_sent:
            logger.info("Email sent successfully")
        else:
            errors.append("Email delivery failed")
    elif no_email:
        logger.info("Email skipped (--no-email flag)")
    else:
        logger.warning("Email not configured; skipping delivery")

    # ── 7. Update state ────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("PHASE 7: Updating state")
    logger.info("=" * 60)

    dedup.mark_seen(analyzed_papers)
    dedup.save()

    tracker = StateTracker()
    tracker.record_run(
        papers_fetched=total_fetched,
        papers_new=len(new_papers),
        papers_analyzed=len(analyzed_papers),
        tokens_used=client.total_tokens,
        cost_estimate=client.total_cost,
        errors=errors if errors else None,
    )
    tracker.save()

    # ── 8. Final summary ───────────────────────────────────────────
    usage = client.usage_summary()
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info("  Papers fetched: %d", total_fetched)
    logger.info("  Papers new: %d", len(new_papers))
    logger.info("  Papers analyzed: %d", len(analyzed_papers))
    logger.info("  Tokens used: %d (input=%d, output=%d)",
                usage["total_tokens"],
                usage["input_tokens"],
                usage["output_tokens"])
    logger.info("  Estimated cost: $%.6f", usage["total_cost"])
    logger.info("  Email sent: %s", email_sent)
    if errors:
        logger.warning("  Errors: %s", errors)
    logger.info("=" * 60)

    return 1 if errors else 0


# ── CLI ────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="econ-brief: Daily economics research briefing automation"
    )
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Only fetch papers, skip LLM analysis and delivery",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch papers and print summary, no analysis",
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Skip email delivery (Markdown is still generated)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--journals",
        type=str,
        default=None,
        help="Path to journals YAML config",
    )
    parser.add_argument(
        "--prompts",
        type=str,
        default=None,
        help="Path to prompts YAML config",
    )

    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    os.makedirs("data", exist_ok=True)
    os.makedirs("output/briefings", exist_ok=True)

    config = load_config(
        journals_path=args.journals,
        prompts_path=args.prompts,
    )

    exit_code = asyncio.run(
        run_pipeline(
            config=config,
            fetch_only=args.fetch_only,
            no_email=args.no_email,
            dry_run=args.dry_run,
        )
    )

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
