import argparse
import asyncio
import gc
import json
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from tracker.config import load_config
from tracker.database import JobRepository
from tracker.dedup import should_skip_dedup
from tracker.filters import check_job_filters
from tracker.logger import get_logger, setup_logging
from tracker.models import Job
from tracker.notifiers.telegram import TelegramNotifier
from tracker.scheduler import run_scheduler
from tracker.scrapers import get_scraper

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = PROJECT_ROOT / "data" / "tier_results"


def _is_playwright_scraper(scraper) -> bool:
    mod = sys.modules.get(type(scraper).__module__)
    return getattr(mod, "PLAYWRIGHT_AVAILABLE", False)


_COMPANY_TIMEOUT_SECONDS = 600
_PLAYWRIGHT_TIMEOUT_SECONDS = 600


async def _scrape_company(company, config, repo, logger) -> tuple[list, int]:
    """Scrape a single company. Returns (matched Jobs, raw jobs seen)."""
    try:
        scraper = get_scraper(company, config.scraper)
    except ValueError as e:
        logger.warning("[%s] %s", company.name, e)
        return []

    raw_jobs = []
    is_playwright = _is_playwright_scraper(scraper)
    timeout = _PLAYWRIGHT_TIMEOUT_SECONDS if is_playwright else _COMPANY_TIMEOUT_SECONDS
    for attempt in range(config.scraper.retry_count):
        try:
            async def _fetch_all():
                jobs = []
                async for job in scraper.fetch():
                    jobs.append(job)
                return jobs

            raw_jobs = await asyncio.wait_for(_fetch_all(), timeout=timeout)
            break
        except asyncio.TimeoutError:
            logger.error("[%s] Timed out after %ds (attempt %d)", company.name, timeout, attempt + 1)
            if is_playwright:
                gc.collect()
            if attempt == config.scraper.retry_count - 1:
                raw_jobs = []
                break
        except (BrokenPipeError, ConnectionError, OSError) as e:
            logger.error("[%s] Playwright pipe error (attempt %d): %s", company.name, attempt + 1, e)
            gc.collect()
            if attempt == config.scraper.retry_count - 1:
                raw_jobs = []
                break
            await asyncio.sleep(5)
        except Exception as e:
            if attempt == config.scraper.retry_count - 1:
                logger.error("[%s] Failed after %d attempts: %s", company.name, attempt + 1, e)
                raw_jobs = []
                break
            await asyncio.sleep(config.scraper.retry_backoff_seconds * (attempt + 1))

    matched = []
    for raw_job in raw_jobs:
        # ponytail: job without a link can't be applied to — drop at source
        if not raw_job.url or not raw_job.url.strip():
            continue
        if config.features.dedup_notifications and should_skip_dedup(raw_job, repo, True):
            continue

        passes, _ = check_job_filters(raw_job, config.filters, skip_location_filter=company.skip_location_filter)
        if not passes:
            continue

        db_job = repo.upsert(raw_job)
        if db_job:
            matched.append(db_job)

    if _is_playwright_scraper(scraper):
        gc.collect()
        await asyncio.sleep(0.5)

    return matched, len(raw_jobs)


async def _run_tier(tier_companies, config, repo, logger) -> tuple[list, int, list[str]]:
    """Scrape a tier — JSON-API scrapers concurrently, Playwright sequentially.
    Returns (matched_jobs, raw_seen, failed_company_names)."""
    sem = asyncio.Semaphore(max(1, config.scraper.max_concurrency))
    jobs: list = []
    raw_total = 0
    failed: list[str] = []

    async def worker(company):
        nonlocal raw_total
        try:
            matched, raw = await _scrape_company(company, config, repo, logger)
            jobs.extend(matched)
            raw_total += raw
        except Exception as e:
            logger.error("[%s] Unexpected error: %s", company.name, e)
            failed.append(company.name)

    async def bounded(company):
        async with sem:
            await worker(company)

    api_tasks = []
    playwright = []
    for company in tier_companies:
        try:
            scraper = get_scraper(company, config.scraper)
        except ValueError as e:
            logger.warning("[%s] %s", company.name, e)
            failed.append(company.name)
            continue
        if _is_playwright_scraper(scraper):
            playwright.append(company)  # memory-heavy: run one at a time
        else:
            api_tasks.append(asyncio.create_task(bounded(company)))

    if api_tasks:
        await asyncio.gather(*api_tasks)
    for company in playwright:
        await worker(company)

    return jobs, raw_total, failed


async def run_tier(tier_name: str, config_path: str) -> dict:
    """Scrape a single tier and save results to disk. Returns stats dict."""
    config = load_config(config_path)
    setup_logging(level=config.logging.level, file_path=config.logging.file)
    logger = get_logger()

    tier_companies = dict(config.companies.by_tier()).get(tier_name, [])
    if not tier_companies:
        logger.warning("Tier '%s' not found or empty", tier_name)
        return {"tier": tier_name, "companies": 0, "jobs": 0, "failed": 0, "elapsed": 0, "job_ids": []}

    logger.info("── Tier: %s (%d companies) ──", tier_name, len(tier_companies))
    start = time.time()
    repo = JobRepository(config.database.path)

    tier_jobs, tier_raw, failed_names = await _run_tier(tier_companies, config, repo, logger)
    elapsed = time.time() - start

    job_ids = [j.id for j in tier_jobs if j.id is not None]
    result = {
        "tier": tier_name,
        "companies": len(tier_companies),
        "jobs": len(tier_jobs),
        "raw": tier_raw,
        "failed": len(failed_names),
        "failed_companies": failed_names,
        "elapsed": elapsed,
        "job_ids": job_ids,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    result_file = RESULTS_DIR / f"{tier_name}.json"
    with open(result_file, "w") as f:
        json.dump(result, f)

    repo.close()
    logger.info("Tier %s done: %d jobs in %.1fs", tier_name, len(tier_jobs), elapsed)
    return result


async def run_pipeline(config_path: str, tier_filter: str | None = None) -> dict:
    config = load_config(config_path)
    setup_logging(level=config.logging.level, file_path=config.logging.file)
    logger = get_logger()

    start_time = time.time()
    logger.info("Starting internship tracker pipeline")

    repo = JobRepository(config.database.path)
    notifier = TelegramNotifier(config.telegram)
    all_matched_jobs = []
    tier_results = []

    for tier_name, tier_companies in config.companies.by_tier():
        if tier_filter and tier_name != tier_filter:
            continue

        logger.info("── Tier: %s (%d companies) ──", tier_name, len(tier_companies))
        tier_start = time.time()

        tier_jobs, tier_raw, failed_names = await _run_tier(tier_companies, config, repo, logger)

        tier_elapsed = time.time() - tier_start
        tier_stats = {
            "tier": tier_name,
            "companies": len(tier_companies),
            "jobs": len(tier_jobs),
            "raw": tier_raw,
            "failed": len(failed_names),
            "failed_companies": failed_names,
            "elapsed": tier_elapsed,
        }
        tier_results.append(tier_stats)
        all_matched_jobs.extend([(job, tier_name) for job in tier_jobs])
        logger.info("Tier %s done: %d jobs in %.1fs", tier_name, len(tier_jobs), tier_elapsed)

        unnotified_in_tier = repo.get_unnotified()
        unnotified_ids = {j.id for j in unnotified_in_tier}
        tier_matched = [(job, tier_name) for job in tier_jobs if job.id in unnotified_ids]

        if tier_matched:
            sent = await notifier.send_tier_digest(tier_name, [j for j, _ in tier_matched], tier_stats)
            if sent:
                for job, _ in tier_matched:
                    repo.mark_notified(job.id)

    if config.aggregator_feeds.enabled and not tier_filter:
        from tracker.scrapers.aggregator import AggregatorScraper
        agg_filters = config.filters.model_copy(
            update={"max_posting_age_days": config.aggregator_feeds.max_posting_age_days}
        )
        agg_jobs = []
        for source in config.aggregator_feeds.sources:
            try:
                agg = AggregatorScraper(source)
                async for raw_job in agg.fetch():
                    if not raw_job.url or not raw_job.url.strip():
                        continue
                    if config.features.dedup_notifications and should_skip_dedup(raw_job, repo, True):
                        continue
                    passes, _ = check_job_filters(raw_job, agg_filters)
                    if not passes:
                        continue
                    db_job = repo.upsert(raw_job)
                    if db_job:
                        agg_jobs.append(db_job)
                        all_matched_jobs.append((db_job, "aggregator"))
            except Exception as e:
                logger.error("[Aggregator] Failed for %s: %s", source.name, e)

        if agg_jobs:
            agg_stats = {"tier": "aggregator", "companies": len(config.aggregator_feeds.sources), "jobs": len(agg_jobs), "failed": 0, "elapsed": 0}
            unnotified = repo.get_unnotified()
            unnotified_ids = {j.id for j in unnotified}
            agg_matched = [j for j in agg_jobs if j.id in unnotified_ids]
            if agg_matched:
                sent = await notifier.send_tier_digest("aggregator", agg_matched, agg_stats)
                if sent:
                    for job in agg_matched:
                        repo.mark_notified(job.id)

    total_companies = config.companies.total if not tier_filter else tier_results[0]["companies"] if tier_results else 0
    total_failed = sum(r["failed"] for r in tier_results)
    total_raw = sum(r["raw"] for r in tier_results)

    # Watchdog: scrapers ran but returned nothing at all — likely blocked, not a quiet day
    if total_companies and total_raw == 0:
        await notifier.send_watchdog(total_companies, total_failed)

    _maybe_prune(repo, config, logger)

    elapsed = time.time() - start_time
    logger.info(
        "Pipeline complete: %d companies | %d failed | %.1fs",
        total_companies, total_failed, elapsed,
    )

    repo.close()
    return {
        "total_scraped": total_companies,
        "passed_filters": len(all_matched_jobs),
        "new_today": len(all_matched_jobs),
        "failed": total_failed,
        "tiers": tier_results,
    }


def run_all_tiers_separate(config_path: str) -> None:
    """Run each tier as a separate subprocess for crash isolation."""
    config = load_config(config_path)
    setup_logging(level=config.logging.level, file_path=config.logging.file)
    logger = get_logger()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    tier_names = [name for name, _ in config.companies.by_tier()]
    logger.info("Running %d tiers as separate subprocesses", len(tier_names))

    for tier_name in tier_names:
        logger.info("=== Starting tier: %s ===", tier_name)
        try:
            result = subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "main.py"), "--run-tier", tier_name, "--config", config_path],
                timeout=2400,
                capture_output=False,
            )
            if result.returncode != 0:
                logger.error("Tier %s exited with code %d", tier_name, result.returncode)
        except subprocess.TimeoutExpired:
            logger.error("Tier %s timed out after %ds", tier_name, 2400)
        except Exception as e:
            logger.error("Tier %s crashed: %s", tier_name, e)

    logger.info("All tiers complete. Aggregating results...")
    _aggregate_and_notify(config_path)


def _maybe_prune(repo: JobRepository, config, logger) -> None:
    if config.database.prune_days > 0:
        pruned = repo.prune(config.database.prune_days)
        if pruned:
            logger.info("Pruned %d jobs not seen in %d days", pruned, config.database.prune_days)


def _aggregate_and_notify(config_path: str) -> None:
    """Read tier results from disk, load matching jobs from DB, send per-tier Telegram digests."""
    config = load_config(config_path)
    setup_logging(level=config.logging.level, file_path=config.logging.file)
    logger = get_logger()

    repo = JobRepository(config.database.path)
    all_matched = []
    tier_results = []

    for result_file in sorted(RESULTS_DIR.glob("*.json")):
        with open(result_file) as f:
            result = json.load(f)
        tier_results.append(result)
        for job_id in result.get("job_ids", []):
            job = repo.get_by_id(job_id)
            if job:
                all_matched.append((job, result["tier"]))

    unnotified = repo.get_unnotified()
    unnotified_ids = {j.id for j in unnotified}
    all_matched = [(job, tier) for job, tier in all_matched if job.id in unnotified_ids]

    total_companies = config.companies.total
    total_failed = sum(r.get("failed", 0) for r in tier_results)

    logger.info("Aggregated: %d jobs from %d tiers", len(all_matched), len(tier_results))

    notifier = TelegramNotifier(config.telegram)

    tier_results_map = {r["tier"]: r for r in tier_results}

    async def _send():
        grouped: dict[str, list[Job]] = {}
        for job, tier in all_matched:
            grouped.setdefault(tier, []).append(job)

        for tier_name, jobs in grouped.items():
            tier_stats = tier_results_map.get(tier_name, {
                "companies": 0, "jobs": len(jobs), "failed": 0, "elapsed": 0
            })
            sent = await notifier.send_tier_digest(tier_name, jobs, tier_stats)
            if sent:
                for job in jobs:
                    repo.mark_notified(job.id)

        if not grouped:
            raw_total = sum(r.get("raw", 0) for r in tier_results)
            if total_companies and raw_total == 0:
                # Watchdog: scrapers ran but returned nothing — likely blocked, not a quiet day
                await notifier.send_watchdog(total_companies, total_failed)
            else:
                stats = {
                    "total_scraped": total_companies,
                    "passed_filters": 0,
                    "new_today": 0,
                    "failed": total_failed,
                    "tiers": tier_results,
                }
                await notifier.send_digest([], stats)

    _maybe_prune(repo, config, logger)
    asyncio.run(_send())
    repo.close()

    for f in RESULTS_DIR.glob("*.json"):
        f.unlink()


async def run_now(config_path: str) -> None:
    await run_pipeline(config_path)


async def daily_job_wrapper(config_path: str):
    return await run_pipeline(config_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Personal Internship Alert System")
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Run the full pipeline immediately and exit",
    )
    parser.add_argument(
        "--run-all-tiers",
        action="store_true",
        help="Run each tier as separate subprocess (crash isolation)",
    )
    parser.add_argument(
        "--run-tier",
        type=str,
        help="Run only the specified tier",
    )
    parser.add_argument(
        "--aggregate",
        action="store_true",
        help="Aggregate tier results and send Telegram",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=str(PROJECT_ROOT / "config.yaml"),
        help="Path to config.yaml",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as a long-lived daemon with APScheduler",
    )
    args = parser.parse_args()

    if args.run_now:
        asyncio.run(run_now(args.config))
    elif args.run_all_tiers:
        run_all_tiers_separate(args.config)
    elif args.run_tier:
        asyncio.run(run_tier(args.run_tier, args.config))
    elif args.aggregate:
        _aggregate_and_notify(args.config)
    elif args.daemon:
        config = load_config(args.config)
        setup_logging(level=config.logging.level, file_path=config.logging.file)
        logger = get_logger()
        logger.info(
            "Starting daemon mode, scheduled for %s %s",
            config.schedule.time,
            config.schedule.timezone,
        )

        async def job_wrapper():
            await run_pipeline(args.config)

        asyncio.run(run_scheduler(config.schedule, job_wrapper))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
