"""
Kula ATS scraper.

Used by Cashfree and other companies that use Kula (careers.kula.ai) for their
careers page. The API is at careers.kula.ai/api/internal/ats_job_posts.
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


class KulaScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)
        self._account_name = getattr(company, "account_name", None) or "cashfree"

    async def fetch(self) -> AsyncIterator[RawJob]:
        api_url = (
            f"https://careers.kula.ai/api/internal/ats_job_posts"
            f"?accountName={self._account_name}&page=1&type=ats_job_post.index&items=99"
        )

        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": f"https://careers.kula.ai/{self._account_name}",
            },
        ) as client:
            try:
                resp = await client.get(api_url)
                if resp.status_code != 200:
                    logger.warning("[Kula] HTTP %d for %s", resp.status_code, self.company)
                    return

                data = resp.json()
                jobs_raw = data.get("data", [])
                if not jobs_raw:
                    logger.warning("[Kula] No jobs found for %s", self.company)
                    return

                for item in jobs_raw:
                    parsed = self._parse_job(item)
                    if parsed:
                        yield parsed

                logger.info("[Kula] %s: %d jobs", self.company, len(jobs_raw))

            except Exception as e:
                logger.error("[Kula] Failed for %s: %s", self.company, e)

    def _parse_job(self, item: dict) -> RawJob | None:
        title = _safe_str(item.get("title")).strip()
        if not title:
            return None

        job_id = item.get("id")
        url = f"https://careers.kula.ai/{self._account_name}/jobs/{job_id}" if job_id else ""

        ats_job = item.get("ats_job", {})

        location = None
        offices = ats_job.get("offices", [])
        if offices and isinstance(offices, list):
            loc = offices[0].get("location", "")
            if loc:
                location = loc

        description_html = _safe_str(ats_job.get("job_description"))
        # Strip HTML tags for plain text
        import re
        description = re.sub(r"<[^>]+>", " ", description_html).strip() or None

        employment_type = _safe_str(ats_job.get("employment_type")).strip() or None

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=url,
            description=description,
            employment_type=employment_type,
            date_posted=None,
            source_ats="kula",
        )
