"""
Arista Networks SmartRecruiters API scraper.

Uses the SmartRecruiters public job search API with JSON (not JSONP)
to fetch all India-based jobs. Simple httpx calls, no Playwright needed.
"""

import logging
from typing import AsyncIterator

import httpx

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper

logger = logging.getLogger("tracker")


class AristaScraper(BaseScraper):
    """Scraper for Arista Networks (SmartRecruiters public API)."""

    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)
        self._api_url = (
            "https://www.smartrecruiters.com/job-api/public/search/"
            "widgets/AristaNetworks/postings"
        )

    async def fetch(self) -> AsyncIterator[RawJob]:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
            },
        ) as client:
            seen: set[str] = set()
            offset = 0
            while offset < 500:
                try:
                    resp = await client.get(
                        self._api_url,
                        params={
                            "dcr_ci": "AristaNetworks",
                            "offset": str(offset),
                            "limit": "100",
                            "jobAdType": "PUBLIC",
                            "langCode": "en",
                            "locationType": "ANY",
                        },
                    )
                    data = resp.json()
                    jobs = data.get("results", [])
                    if not jobs:
                        break

                    for j in jobs:
                        location = j.get("location", "")
                        loc_lower = location.lower()

                        if not any(
                            x in loc_lower
                            for x in [
                                "india",
                                "bengaluru",
                                "bangalore",
                                "hyderabad",
                                "pune",
                                "mumbai",
                                "chennai",
                                "gurgaon",
                                "noida",
                                "delhi",
                            ]
                        ):
                            continue

                        vacancy_id = j.get("vacancyName", "") + "|" + location
                        if vacancy_id in seen:
                            continue
                        seen.add(vacancy_id)

                        ref = j.get("refNumber", "")
                        job_url = f"https://www.arista.com/en/careers#{ref}"

                        yield RawJob(
                            company="Arista Networks",
                            title=j.get("vacancyName", ""),
                            location=location,
                            url=job_url,
                            description=None,
                            employment_type=j.get("typeOfEmployment"),
                            date_posted=None,
                            source_ats="custom-api",
                        )

                    offset += 100
                    if offset >= data.get("totalFound", 0):
                        break
                except Exception as exc:
                    logger.warning("Arista API error at offset %d: %s", offset, exc)
                    break
