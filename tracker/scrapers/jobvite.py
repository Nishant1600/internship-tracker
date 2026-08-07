"""
Jobvite scraper.

Jobvite is an applicant tracking system used by some companies.
Their API structure is not publicly documented, so this is a stub
that will need to be refined once we can inspect actual responses.

BEST-EFFORT ONLY.
"""

import logging
from typing import AsyncIterator, Any

import httpx

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper

logger = logging.getLogger("tracker")


def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    return str(val)


class JobviteScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        try:
            async with httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
                follow_redirects=True,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                },
            ) as client:
                resp = await client.get(self.url)
                if resp.status_code == 404:
                    logger.warning("[Jobvite] 404 for %s", self.company)
                    return
                resp.raise_for_status()

                data = resp.json()
                jobs = self._extract_jobs(data)
                if not jobs:
                    logger.warning("[Jobvite] No jobs found for %s", self.company)
                    return

                for item in jobs:
                    parsed = self._parse_job(item)
                    if parsed:
                        yield parsed
        except Exception as e:
            logger.error("[Jobvite] Failed for %s: %s", self.company, e)

    def _extract_jobs(self, data: Any) -> list[dict]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("jobs", "data", "results", "items", "requisitions"):
                if key in data and isinstance(data[key], list):
                    return data[key]
                if key in data and isinstance(data[key], dict):
                    return self._extract_jobs(data[key])
        return []

    def _parse_job(self, item: dict) -> RawJob | None:
        title = _safe_str(
            item.get("title") or item.get("jobTitle") or item.get("name") or ""
        ).strip()
        if not title:
            return None

        location = _safe_str(
            item.get("location") or item.get("jobLocation") or ""
        ).strip() or None

        description = _safe_str(
            item.get("description") or item.get("jobDescription") or ""
        ).strip() or None

        url = _safe_str(item.get("url") or item.get("jobUrl") or item.get("applyUrl") or "").strip()
        if not url:
            job_id = item.get("jobId") or item.get("id") or item.get("requisitionId")
            if job_id:
                url = f"{self.url.rstrip('/')}/jobs/{job_id}"

        date_posted = _safe_str(
            item.get("datePosted") or item.get("postedDate") or item.get("createdAt") or ""
        ).strip() or None

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=url,
            description=description,
            employment_type=None,
            date_posted=date_posted,
            source_ats="jobvite",
        )
