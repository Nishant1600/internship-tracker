from datetime import datetime, timezone
from typing import AsyncIterator, Any

import httpx

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper


def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float)):
        return str(val)
    return str(val)


def _parse_lever_date(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        try:
            dt = datetime.fromtimestamp(val / 1000, tz=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (OSError, ValueError, OverflowError):
            return None
    s = str(val).strip()
    return s if s else None


class LeverScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            resp = await client.get(self.url)
            if resp.status_code == 404:
                self._log_warning(f"Board returned 404 for {self.company}")
                return
            resp.raise_for_status()
            data = resp.json()

            if not isinstance(data, list):
                self._log_warning(
                    f"Unexpected response format (expected list, got {type(data).__name__}) "
                    f"for {self.company}"
                )
                return

            for posting in data:
                parsed = self._parse_posting(posting)
                if parsed:
                    yield parsed

    def _parse_posting(self, posting: dict[str, Any]) -> RawJob | None:
        title = _safe_str(posting.get("text") or "").strip()
        if not title:
            title = _safe_str(posting.get("title") or "").strip()
        if not title:
            return None

        categories = posting.get("categories") or {}
        location = _safe_str(categories.get("location")).strip() or None
        employment_type = _safe_str(categories.get("commitment")).strip() or None
        team = _safe_str(categories.get("team")).strip() or None

        description = _safe_str(posting.get("description")).strip() or None
        description_plain = _safe_str(posting.get("descriptionPlain")).strip() or None
        if description is None:
            description = description_plain

        date_posted = _parse_lever_date(posting.get("createdAt"))
        absolute_url = _safe_str(posting.get("hostedUrl")).strip() or None

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=absolute_url or "",
            description=description,
            employment_type=employment_type,
            date_posted=date_posted,
            source_ats="lever",
        )

    def _log_warning(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").warning("[Lever] %s", msg)
