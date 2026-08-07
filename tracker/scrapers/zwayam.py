"""
Zwayam ATS scraper.

Used by CureFit (cult.fit) and other Indian companies.
Zwayam exposes a POST API at public.zwayam.com/jobs/search
that accepts multipart form data with filter criteria.
"""

import json
import logging
from typing import AsyncIterator, Any

import httpx

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper

logger = logging.getLogger("tracker")


class ZwayamScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)
        # Extract companyId from config or URL
        self._company_id = getattr(company, "company_id", None) or "MTU0NzA="
        self._domain = getattr(company, "domain", None) or "careers.cult.fit"

    async def fetch(self) -> AsyncIterator[RawJob]:
        api_url = "https://public.zwayam.com/jobs/search"
        page_size = 10
        start = 0
        total = None

        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Origin": f"https://{self._domain}",
                "Referer": f"https://{self._domain}/",
            },
        ) as client:
            while True:
                filter_cri = json.dumps({
                    "paginationStartNo": start,
                    "selectedCall": "sort",
                    "sortCriteria": {"name": "modifiedDate", "isAscending": False},
                    "anyOfTheseWords": "",
                })

                try:
                    resp = await client.post(
                        api_url,
                        data={
                            "filterCri": filter_cri,
                            "domain": self._domain,
                            "companyId": self._company_id,
                        },
                    )
                    if resp.status_code != 200:
                        logger.warning(
                            "[Zwayam] HTTP %d for %s", resp.status_code, self.company
                        )
                        return

                    body = resp.json()
                    if body.get("code") != 200:
                        logger.warning(
                            "[Zwayam] API error for %s: %s",
                            self.company, body.get("message"),
                        )
                        return

                    data = body.get("data", {})
                    jobs_raw = data.get("data", [])
                    if total is None:
                        total = data.get("totalCount", 0)

                    for item in jobs_raw:
                        parsed = self._parse_job(item)
                        if parsed:
                            yield parsed

                    logger.info("[Zwayam] Page %d: %d jobs for %s", start // page_size + 1, len(jobs_raw), self.company)

                    start += page_size
                    if start >= total or not jobs_raw:
                        break

                except Exception as e:
                    logger.error("[Zwayam] Failed for %s: %s", self.company, e)
                    return

    def _parse_job(self, item: dict) -> RawJob | None:
        src = item.get("_source", item)

        title = (src.get("jobTitle") or "").strip()
        if not title:
            return None

        location = (src.get("officeLocation") or "").strip() or None

        job_url = (src.get("jobUrl") or "").strip()
        if job_url and not job_url.startswith("http"):
            job_url = f"https://{self._domain}/job/{job_url}"

        description_parts = []
        if src.get("jobDescription"):
            description_parts.append(src["jobDescription"])
        if src.get("responsibility"):
            description_parts.append(src["responsibility"])
        description = "\n".join(description_parts).strip() or None

        min_exp = src.get("minYearOfExperience")
        max_exp = src.get("maxYrsOfExperience")
        employment_type = None
        if min_exp is not None and max_exp is not None:
            employment_type = f"{min_exp}-{max_exp} years"

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=job_url,
            description=description,
            employment_type=employment_type,
            date_posted=None,
            source_ats="zwayam",
        )
