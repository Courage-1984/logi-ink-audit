#!/usr/bin/env python3
"""CLI entry point for the Logi-Ink asynchronous web auditing suite."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

from src.auditor_geo_aeo import GeoAeoAuditor
from src.auditor_seo import SeoAuditor
from src.auditor_technical import TechnicalAuditor
from src.crawler import AsyncCrawler
from src.emailer import send_audit_report
from src.history import analyse_historical_trends
from src.reporter import AuditReporter, summarise_critical_failures

DEFAULT_BASE_URL = "https://logi-ink.co.za"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Asynchronous Technical SEO, GEO, and AEO audit suite for logi-ink.co.za "
            "(and compatible sites)."
        )
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Site origin to audit (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="Maximum concurrent HTTP requests (default: 8)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Per-request timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional cap on the number of pages to crawl",
    )
    parser.add_argument(
        "--output-dir",
        default="audit-reports",
        help="Directory for Excel reports (default: audit-reports)",
    )
    parser.add_argument(
        "--url",
        action="append",
        dest="urls",
        default=None,
        help="Audit a specific URL (repeatable). Skips sitemap discovery when set.",
    )
    parser.add_argument(
        "--skip-email",
        action="store_true",
        help="Skip SMTP email dispatch even when credentials are configured",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )


async def run_audit(args: argparse.Namespace) -> Path:
    logger = logging.getLogger("main")
    crawler = AsyncCrawler(
        args.base_url,
        concurrency=args.concurrency,
        timeout_seconds=args.timeout,
        max_pages=args.max_pages,
    )

    logger.info("Starting crawl for %s", args.base_url)
    pages = await crawler.crawl(urls=args.urls)
    if not pages:
        raise SystemExit("No pages were fetched; aborting report generation.")

    seo_auditor = SeoAuditor(brand_name="Logi-Ink", base_url=args.base_url)
    geo_auditor = GeoAeoAuditor()
    technical_auditor = TechnicalAuditor(base_url=args.base_url)

    seo_results = []
    geo_results = []
    technical_results = []
    logger.info("Evaluating AI chunking patterns and terminology standards...")
    for page in pages:
        logger.info(
            "Auditing %s [%s] (%.0f ms, %.1f KB, %d DOM nodes)",
            page.url,
            page.status_code or "ERR",
            page.latency_ms,
            page.payload_kb,
            page.dom_node_count,
        )
        seo_results.append(seo_auditor.audit(page))
        geo_results.append(geo_auditor.audit(page))
        technical_results.append(technical_auditor.audit(page))

    delta = analyse_historical_trends(
        args.output_dir,
        seo_results,
        geo_results,
        technical_results,
        as_of=datetime.now(),
    )

    reporter = AuditReporter(output_dir=args.output_dir)
    report_path = reporter.write(
        seo_results,
        geo_results,
        technical_results,
        base_url=args.base_url,
        report_date=datetime.now(),
        delta=delta,
    )

    critical_summary = summarise_critical_failures(
        seo_results,
        geo_results,
        technical_results,
    )

    avg_seo = sum(result.score for result in seo_results) / len(seo_results)
    avg_geo = sum(result.geo_score for result in geo_results) / len(geo_results)
    avg_aeo = sum(result.aeo_score for result in geo_results) / len(geo_results)
    avg_technical = sum(result.technical_score for result in technical_results) / len(
        technical_results
    )
    local_pass = sum(1 for result in geo_results if result.local_seo_compliance)
    terminology_flags = sum(1 for result in seo_results if not result.terminology_ok)
    chunk_ready = sum(1 for result in geo_results if result.ai_chunking_ready)
    bloat_pages = sum(1 for result in technical_results if not result.dom_weight_ok)
    logger.info("Pages audited : %d", len(pages))
    logger.info("Average SEO   : %.1f%%", avg_seo)
    logger.info("Average GEO   : %.1f%%", avg_geo)
    logger.info("Average AEO   : %.1f%%", avg_aeo)
    logger.info("Average Tech  : %.1f%%", avg_technical)
    logger.info("SA local Pass : %d / %d", local_pass, len(geo_results))
    logger.info("Terminology   : %d page(s) with issues", terminology_flags)
    logger.info("AI chunking   : %d / %d ready", chunk_ready, len(geo_results))
    logger.info("DOM bloat     : %d page(s)", bloat_pages)
    logger.info("Delta summary : %s", delta.get("summary_line", ""))
    logger.info("Critical fails: %d", len(critical_summary))
    for line in critical_summary[:20]:
        logger.warning("  %s", line)
    if len(critical_summary) > 20:
        logger.warning("  … and %d more", len(critical_summary) - 20)
    logger.info("Report written: %s", report_path.resolve())

    if args.skip_email:
        logger.info("Email dispatch skipped (--skip-email).")
    else:
        send_audit_report(
            str(report_path.resolve()),
            critical_summary,
            base_url=args.base_url,
            delta=delta,
        )

    return report_path


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    try:
        asyncio.run(run_audit(args))
    except KeyboardInterrupt:
        logging.getLogger("main").warning("Interrupted by user.")
        return 130
    except SystemExit as exc:
        logging.getLogger("main").error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
