from typing import AsyncIterator, Any

import httpx

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper


class BambooHRScraper(BaseScraper):
    """
    BambooHR Public API.
    GET https://{company}.bamboohr.com/jobs/public/

    The company subdomain is extracted from the configured URL.
    """

    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            try:
                resp = await client.get(self.url)
                if resp.status_code == 404:
                    self._log_warning(f"Board returned 404 for {self.company}")
                    return
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                self._log_error(f"HTTP {e.response.status_code} for {self.company}: {e}")
                return

            if isinstance(data, dict):
                items = data.get("result") or data.get("jobs") or [data]
            elif isinstance(data, list):
                items = data
            else:
                items = []

            for item in items:
                if not isinstance(item, dict):
                    continue
                parsed = self._parse_job(item)
                if parsed:
                    yield parsed

    def _parse_job(self, item: dict[str, Any]) -> RawJob | None:
        title = str(item.get("jobTitle") or item.get("title") or item.get("name") or "").strip()
        if not title:
            return None

        location = str(item.get("location") or item.get("city") or "").strip() or None

        department = item.get("department") or {}
        if isinstance(department, dict):
            department_name = str(department.get("label") or department.get("name") or "").strip() or None
        else:
            department_name = str(department).strip() if department else None

        employment_type = str(item.get("employmentType") or item.get("type") or "").strip() or None
        description = str(item.get("description") or item.get("jobDescription") or item.get("summary") or "").strip() or None
        date_posted = str(item.get("postedDate") or item.get("datePosted") or item.get("date") or "").strip() or None
        absolute_url = str(item.get("url") or item.get("applyUrl") or item.get("externalPath") or "").strip() or None

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=absolute_url or "",
            description=description,
            employment_type=employment_type,
            date_posted=date_posted,
            source_ats="bamboohr",
        )

    def _log_warning(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").warning("[BambooHR] %s", msg)

    def _log_error(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").error("[BambooHR] %s", msg)
