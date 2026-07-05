import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from tracker.config import load_config
from tracker.database import JobRepository
from tracker.dedup import should_skip_dedup
from tracker.filters import check_job_filters
from tracker.logger import get_logger, setup_logging
from tracker.matching.hiring_agent import HiringAgentAdapter
from tracker.matching.job_matcher import JobMatcher
from tracker.matching.resume_fallback import HEMANG_RESUME_FALLBACK
from tracker.models import MatchResult
from tracker.notifiers.telegram import TelegramNotifier, format_digest
from tracker.scheduler import run_scheduler
from tracker.scrapers import get_scraper

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent


async def run_pipeline(config_path: str) -> dict:
    config = load_config(config_path)
    setup_logging(level=config.logging.level, file_path=config.logging.file)
    logger = get_logger()

    logger.info("Starting internship tracker pipeline")
    logger.info("Configuration: %d companies | filters: %s", len(config.companies), bool(config.filters.role_keywords.include))

    repo = JobRepository(config.database.path)
    resume = None

    if config.features.hiring_agent_scoring:
        adapter = HiringAgentAdapter(config.hiring_agent)
        resume = adapter.get_structured_resume()
    else:
        resume = HEMANG_RESUME_FALLBACK

    matcher = JobMatcher()
    matched_jobs = []
    stats = {
        "total_scraped": len(config.companies),
        "passed_filters": 0,
        "new_today": 0,
        "failed": 0,
        "above_threshold": 0,
    }

    for company in config.companies:
        try:
            scraper = get_scraper(company, config.scraper)
        except ValueError as e:
            logger.warning("[%s] %s", company.name, e)
            stats["failed"] += 1
            continue

        raw_jobs = []
        for attempt in range(config.scraper.retry_count):
            try:
                async for job in scraper.fetch():
                    raw_jobs.append(job)
                break
            except Exception as e:
                if attempt == config.scraper.retry_count - 1:
                    logger.error("[%s] Failed after %d attempts: %s", company.name, attempt + 1, e)
                    stats["failed"] += 1
                    raw_jobs = []
                    break
                await asyncio.sleep(config.scraper.retry_backoff_seconds * (attempt + 1))

        for raw_job in raw_jobs:
            if config.features.dedup_notifications and should_skip_dedup(raw_job, repo, True):
                continue

            passes, _ = check_job_filters(raw_job, config.filters)
            if not passes:
                continue

            stats["passed_filters"] += 1

            match = matcher.score(raw_job, resume) if resume else MatchResult(score=0, reasons=[])

            if match.score < config.filters.minimum_match_score:
                continue

            stats["above_threshold"] += 1

            db_job = repo.upsert(raw_job)
            if db_job:
                repo.set_match(db_job.id, match.score, match.reasons)
                matched_jobs.append(db_job)
                if not repo.is_notified(raw_job):
                    stats["new_today"] += 1

    all_matches = repo.get_unnotified()
    all_matches.sort(key=lambda j: j.match_score or 0, reverse=True)

    logger.info(
        "Pipeline complete: %d/%d companies | %d passed filters | %d new today | %d failed",
        stats["total_scraped"] - stats["failed"],
        stats["total_scraped"],
        stats["passed_filters"],
        stats["new_today"],
        stats["failed"],
    )

    notifier = TelegramNotifier(config.telegram)
    resume_score = None
    if resume:
        try:
            skill_score = min(len(resume.skills), 30)
            project_score = min(len(resume.projects) * 15, 30)
            work_score = min(len(resume.work) * 20, 25)
            edu_score = 15 if resume.education else 0
            resume_score = skill_score + project_score + work_score + edu_score
            resume_score = min(resume_score, 100)
        except Exception:
            pass

    await notifier.send_digest(all_matches, resume_score, stats)

    repo.close()
    return stats


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
