import os
from datetime import datetime, timezone
from typing import Optional

from telegram import Bot
from telegram.error import TelegramError

from tracker.config import TelegramConfig
from tracker.logger import get_logger
from tracker.models import Job
from tracker.notifiers.base import Notifier

logger = get_logger()


def format_digest(
    jobs: list[Job],
    resume_score: Optional[int],
    stats: dict,
    max_jobs: int = 25,
) -> str:
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%d %b %Y")

    lines: list[str] = []
    lines.append(f"📅 Daily Internship Digest — {date_str}")
    lines.append("")

    if resume_score is not None:
        lines.append(f"Resume Quality Score: {resume_score}/100  (from HackerRank Hiring Agent)")
        lines.append("")

    displayed = jobs[:max_jobs]
    for i, job in enumerate(displayed, 1):
        title = f"{job.company} — {job.title}"
        lines.append(f"{i}. {title}")

        location = job.location or "Location not specified"
        score_str = f"  🎯 {job.match_score}/100" if job.match_score is not None else ""
        lines.append(f"   📍 {location}{score_str}")

        if job.match_reasons:
            try:
                import json
                reasons = json.loads(job.match_reasons)
                if reasons and reasons != ["No skills matched"]:
                    reasons_str = ", ".join(r.capitalize() for r in reasons[:6])
                    lines.append(f"   ✅ Matched: {reasons_str}")
            except (json.JSONDecodeError, TypeError):
                pass

        if job.url:
            lines.append(f"   🔗 {job.url}")

        lines.append("")

    total_scraped = stats.get("total_scraped", 0)
    passed_filters = stats.get("passed_filters", 0)
    above_threshold = stats.get("above_threshold", 0)
    new_today = stats.get("new_today", 0)
    failed = stats.get("failed", 0)

    lines.append("─" * 40)
    lines.append(
        f"📊 Run summary: {total_scraped} companies scraped · {passed_filters} jobs found"
    )
    if above_threshold > 0:
        lines.append(f"   → {passed_filters} passed filters · {above_threshold} above score threshold · {new_today} new today")
    else:
        lines.append(f"   → {passed_filters} passed filters · {new_today} new today")
    if failed:
        lines.append(f"   ⚠️  {failed} companies failed (see logs)")

    return "\n".join(lines)


class TelegramNotifier(Notifier):
    def __init__(self, config: TelegramConfig) -> None:
        self._config = config
        self._bot_token: Optional[str] = None
        self._chat_id: Optional[str] = None

    def _load_secrets(self) -> None:
        if self._bot_token is None:
            self._bot_token = os.environ.get("BOT_TOKEN")
        if self._chat_id is None:
            self._chat_id = os.environ.get("CHAT_ID")

    async def send_digest(
        self,
        jobs: list[Job],
        resume_score: Optional[int],
        stats: dict,
    ) -> bool:
        if not self._config.enabled:
            logger.info("Telegram notifier disabled")
            return False

        self._load_secrets()
        if not self._bot_token or not self._chat_id:
            logger.warning(
                "BOT_TOKEN or CHAT_ID not set in environment. "
                "Digest printed to log instead."
            )
            message = format_digest(
                jobs, resume_score, stats, self._config.max_jobs_per_digest
            )
            logger.info("Digest message:\n%s", message)
            return False

        if not jobs and not self._config.send_if_empty:
            logger.info("No jobs to notify and send_if_empty is false")
            return False

        message = format_digest(
            jobs, resume_score, stats, self._config.max_jobs_per_digest
        )

        try:
            bot = Bot(token=self._bot_token)
            await bot.send_message(
                chat_id=self._chat_id,
                text=message,
                disable_web_page_preview=True,
            )
            logger.info("Digest sent to Telegram (chat_id=%s)", self._chat_id)
            return True
        except TelegramError as e:
            logger.error("Failed to send Telegram message: %s", e)
            return False
