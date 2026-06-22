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
    # Quiet down noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("arxiv").setLevel(logging.WARNING)


# ── Pipeline steps ─────────────────────────────────────────────────

async def run_pipeline(
    config,
    fetch_only: bool = False,
    no_email: bool = False,
    dry_run: bool = False,
) -> int:
    """Run the complete econ-brief pipeline.

    Returns exit code (0 = success, 1 = error).
    """
    today = date.today()
    errors: list[str] = []
    logger = logging.getLogger("pipeline")

    # ── 0. Validate configuration ──────────────────────────────────
    if not dry_run and not fetch_only:
        if not config.anthropic_api_key:
            logger.error("ANTHROPIC_API_KEY environment variable is required")
            return 1

    # ── 1. Fetch papers from all sources ───────────────────────────
    logger.info("=" * 60)
    logger.info("PHASE 1: Fetching papers from all sources")
    logger.info("=" * 60)

    all_papers = await fetch_all(
        intl_journals=config.intl_journals,
        chinese_journals=config.chinese_journals,
        lookback_days=config.lookback_days,
        email=config.openalex_email,
    )

    total_fetched = len(all_papers)
    logger.info("Total fetched: %d papers", total_fetched)

    if not all_papers:
        logger.info("No papers fetched. Exiting.")
        return 0

    if fetch_only or dry_run:
        # Print summary and exit
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

    # ── 3. Stage 1: Relevance scoring (Haiku) ──────────────────────
    logger.info("=" * 60)
    logger.info("PHASE 3: Stage 1 — Relevance scoring (Haiku)")
    logger.info("=" * 60)

    client = LLMClient(api_key=config.anthropic_api_key)
    scorer = RelevanceScorer(
        client=client,
        prompts=config.prompts,
        model=config.haiku_model,
    )
    scored_papers = scorer.score_papers(new_papers)

    # Filter by relevance
    top_papers = [
        p
        for p in scored_papers
        if (p.relevance_score or 0) >= config.min_relevance_score
    ]
    top_papers.sort(key=lambda p: p.relevance_score or 0, reverse=True)
    top_papers = top_papers[: config.max_stage2_papers]

    logger.info(
        "Papers above relevance threshold (%.1f): %d (capped at %d)",
        config.min_relevance_score,
        len(top_papers),
        config.max_stage2_papers,
    )

    if not top_papers:
        logger.info("No papers above relevance threshold. Exiting.")
        dedup.mark_seen(new_papers)
        dedup.save()
        return 0

    # ── 4. Stage 2: Deep analysis (Sonnet) ─────────────────────────
    logger.info("=" * 60)
    logger.info("PHASE 4: Stage 2 — Deep analysis (Sonnet)")
    logger.info("=" * 60)

    analyzer = DeepAnalyzer(
        client=client,
        prompts=config.prompts,
        model=config.sonnet_model,
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

    # Markdown
    md_gen = MarkdownGenerator()
    md_content = md_gen.generate(
        analyzed_papers, summary, today, total_fetched
    )
    md_path = md_gen.save(md_content, today)
    logger.info("Markdown briefing: %s", md_path)

    # HTML email
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

    # Track run statistics
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
    logger.info("  Cache: read=%d, write=%d tokens",
                usage.get("cache_read_tokens", 0),
                usage.get("cache_write_tokens", 0))
    logger.info("  Estimated cost: $%.4f", usage["total_cost"])
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

    # Ensure data/output directories exist
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
