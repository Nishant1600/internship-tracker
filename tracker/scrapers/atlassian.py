"""
Atlassian scraper.

Uses the Jibe API at join.atlassian.com/api/jobs to fetch job listings.
Supports pagination and country filtering.
"""

import logging
from typing import AsyncIterator

import httpx

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper

logger = logging.getLogger("tracker")

ATLASSIAN_API = "https://join.atlassian.com/api/jobs"


class AtlassianScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url or ATLASSIAN_API, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                page = 1
                while True:
                    resp = await client.get(
                        ATLASSIAN_API,
                        params={"country": "India", "page": page},
                        follow_redirects=True,
                    )
                    if resp.status_code != 200:
                        logger.warning(
                            "[Atlassian] API returned %d on page %d", resp.status_code, page
                        )
                        break

                    data = resp.json()
                    jobs = data.get("jobs", [])
                    if not jobs:
                        break

                    for j in jobs:
                        job_data = j.get("data", {})
                        title = job_data.get("title", "")
                        location = job_data.get("full_location", "") or job_data.get("location_name", "")
                        apply_url = job_data.get("apply_url", "")
                        posted = job_data.get("posted_date")

                        if title:
                            yield RawJob(
                                company=self.company,
                                title=title,
                                location=location,
                                url=apply_url,
                                description=None,
                                employment_type=job_data.get("employment_type"),
                                date_posted=posted,
                                source_ats="atlassian",
                            )

                    page += 1

        except Exception as e:
            logger.error("[Atlassian] Failed for %s: %s", self.company, e)
