import os
from datetime import datetime, timezone

from telegram import Bot
from telegram.error import TelegramError

from tracker.config import TelegramConfig
from tracker.filters import parse_posted_date
from tracker.logger import get_logger
from tracker.models import Job
from tracker.notifiers.base import Notifier

logger = get_logger()

TIER_EMOJI = {
    "easy": "🟢",
    "medium-easy": "🟡",
    "medium": "🟠",
    "medium-hard": "🔴",
    "hard": "💀",
    "aggregator": "🔗",
    "default": "📋",
}

TELEGRAM_MAX_LEN = 4096


def _format_tier_header(tier: str, job_count: int) -> str:
    emoji = TIER_EMOJI.get(tier, "📋")
    label = tier.replace("-", " ").title()
    return f"{emoji} {label} — {job_count} new jobs"


def _age_str(date_posted: str | None) -> str | None:
    dt = parse_posted_date(date_posted)
    if not dt:
        return None
    days = (datetime.now(timezone.utc) - dt).days
    if days < 0:
        return "new"
    if days == 0:
        return "today"
    return f"{days}d ago"


def _format_job_lines(jobs: list[Job]) -> list[str]:
    lines: list[str] = []
    for job in jobs:
        title = f"{job.company} — {job.title}"
        lines.append(f"  {title}")
        meta = []
        if job.location:
            meta.append(job.location)
        age = _age_str(job.date_posted)
        if age:
            meta.append(age)
        if meta:
            lines.append(f"  {' · '.join(meta)}")
        if job.url:
            lines.append(f"  {job.url}")
        lines.append("")
    return lines


def _split_message(header: str, body_lines: list[str]) -> list[str]:
    """Split into multiple messages, each under TELEGRAM_MAX_LEN."""
    messages: list[str] = []
    current_lines: list[str] = []
    current_len = len(header) + 2

    for line in body_lines:
        line_len = len(line) + 1
        if current_len + line_len > TELEGRAM_MAX_LEN - 50:
            messages.append(header + "\n\n" + "\n".join(current_lines))
            header = header.split("—")[0].strip()
            current_lines = []
            current_len = len(header) + 2
        current_lines.append(line)
        current_len += line_len

    if current_lines:
        messages.append(header + "\n\n" + "\n".join(current_lines))

    return messages


def format_digest(
    jobs: list[tuple[Job, str]],
    stats: dict,
    max_jobs: int = 50,
) -> str:
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%d %b %Y")

    lines: list[str] = []
    lines.append(f"Internship Digest — {date_str}")
    lines.append("")

    if not jobs:
        lines.append("No new matching internships found.")
        lines.append("")
        lines.append(_format_summary(stats))
        return "\n".join(lines)

    grouped: dict[str, list[Job]] = {}
    for job, tier in jobs:
        grouped.setdefault(tier, []).append(job)

    displayed = 0
    tier_order = ["easy", "medium-easy", "medium", "medium-hard", "hard", "aggregator", "default"]
    for tier in tier_order:
        if tier not in grouped:
            continue
        tier_jobs = grouped[tier]
        emoji = TIER_EMOJI.get(tier, "📋")
        tier_label = tier.replace("-", " ").title()
        lines.append(f"{emoji} {tier_label} ({len(tier_jobs)})")

        for job in tier_jobs[:max_jobs - displayed]:
            title = f"{job.company} — {job.title}"
            lines.append(f"  {title}")
            if job.url:
                lines.append(f"  {job.url}")
            lines.append("")
            displayed += 1

        if len(tier_jobs) > max_jobs - displayed:
            remaining = len(tier_jobs) - (max_jobs - displayed)
            lines.append(f"  ...and {remaining} more {tier_label} jobs")
            lines.append("")
            break

    lines.append(_format_summary(stats))
    return "\n".join(lines)


def _format_summary(stats: dict) -> str:
    total_scraped = stats.get("total_scraped", 0)
    passed_filters = stats.get("passed_filters", 0)
    failed = stats.get("failed", 0)
    tiers = stats.get("tiers", [])

    parts = [f"{total_scraped} companies scraped", f"{passed_filters} jobs found"]
    if failed:
        parts.append(f"{failed} failed")
    summary = " | ".join(parts)

    if tiers:
        lines = [summary]
        for t in tiers:
            emoji = TIER_EMOJI.get(t["tier"], "📋")
            lines.append(f"  {emoji} {t['tier']}: {t['jobs']}/{t['companies']} in {t['elapsed']:.0f}s")
        return "\n".join(lines)
    return summary


class TelegramNotifier(Notifier):
    def __init__(self, config: TelegramConfig) -> None:
        self._config = config
        self._bot_token: str | None = None
        self._chat_id: str | None = None

    def _load_secrets(self) -> None:
        if self._bot_token is None:
            self._bot_token = os.environ.get("BOT_TOKEN")
        if self._chat_id is None:
            self._chat_id = os.environ.get("CHAT_ID")

    def _check_config(self) -> bool:
        self._load_secrets()
        if not self._config.enabled:
            logger.info("Telegram notifier disabled")
            return False
        if not self._bot_token or not self._chat_id:
            logger.warning(
                "BOT_TOKEN or CHAT_ID not set in environment. "
                "Digest printed to log instead."
            )
            return False
        return True

    async def _send_messages(self, messages: list[str]) -> bool:
        """Send one or more messages to Telegram, logging any that fail."""
        if not self._check_config():
            for msg in messages:
                logger.info("Telegram message:\n%s", msg)
            return False

        bot = Bot(token=self._bot_token)
        sent_any = False
        for msg in messages:
            if not msg.strip():
                continue
            try:
                await bot.send_message(
                    chat_id=self._chat_id,
                    text=msg,
                    disable_web_page_preview=True,
                )
                sent_any = True
            except TelegramError as e:
                logger.error("Failed to send Telegram message: %s", e)
        return sent_any

    async def send_tier_digest(
        self,
        tier_name: str,
        jobs: list[Job],
        tier_stats: dict,
    ) -> bool:
        """Send a digest for a single tier, capped at max_jobs_per_digest."""
        if not jobs:
            return False

        cap = self._config.max_jobs_per_digest
        body_lines = _format_job_lines(jobs[:cap])
        if len(jobs) > cap:
            body_lines.append(f"  ...and {len(jobs) - cap} more")
            body_lines.append("")

        header = _format_tier_header(tier_name, len(jobs))
        summary = (
            f"{tier_stats.get('companies', 0)} companies | "
            f"{len(jobs)} new jobs | "
            f"{tier_stats.get('failed', 0)} failed | "
            f"{tier_stats.get('elapsed', 0):.0f}s"
        )

        messages = _split_message(header, body_lines)
        if messages:
            messages[-1] = messages[-1] + "\n\n" + summary

        logger.info(
            "Tier %s: sending %d jobs in %d message(s)",
            tier_name, len(jobs), len(messages),
        )
        return await self._send_messages(messages)

    async def send_watchdog(self, companies_scraped: int, failed: int) -> bool:
        """Forced alert: scrapers ran but returned zero jobs. Bypasses send_if_empty."""
        text = f"⚠️ Tracker scraped {companies_scraped} companies and found 0 jobs"
        if failed:
            text += f" ({failed} scrapers failed)"
        text += ".\nScrapers may be blocked or career pages changed — check the run logs."
        logger.warning(text)
        return await self._send_messages([text])

    async def send_digest(
        self,
        jobs: list[tuple[Job, str]],
        stats: dict,
    ) -> bool:
        """Send the full pipeline digest, splitting across messages if needed."""
        if not self._check_config():
            message = format_digest(jobs, stats, self._config.max_jobs_per_digest)
            logger.info("Digest message:\n%s", message)
            return False

        if not jobs and not self._config.send_if_empty:
            logger.info("No jobs to notify and send_if_empty is false")
            return False

        now = datetime.now(timezone.utc)
        date_str = now.strftime("%d %b %Y")
        header = f"Internship Digest — {date_str}"

        grouped: dict[str, list[Job]] = {}
        for job, tier in jobs:
            grouped.setdefault(tier, []).append(job)

        body_lines: list[str] = []
        tier_order = ["easy", "medium-easy", "medium", "medium-hard", "hard", "aggregator", "default"]
        for tier in tier_order:
            if tier not in grouped:
                continue
            tier_jobs = grouped[tier]
            emoji = TIER_EMOJI.get(tier, "📋")
            tier_label = tier.replace("-", " ").title()
            body_lines.append(f"{emoji} {tier_label} ({len(tier_jobs)})")
            body_lines.extend(_format_job_lines(tier_jobs))

        summary = _format_summary(stats)
        messages = _split_message(header, body_lines)
        if messages:
            messages[-1] = messages[-1] + "\n\n" + summary

        logger.info(
            "Pipeline digest: %d jobs in %d message(s)",
            len(jobs), len(messages),
        )
        return await self._send_messages(messages)
