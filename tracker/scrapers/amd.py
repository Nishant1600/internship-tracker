"""
AMD careers API scraper.

Uses the AMD careers JSON API at careers.amd.com/api/jobs with
location=India filter. Fetches both general and student/intern roles.
Simple httpx calls, no Playwright needed.
"""

import logging
from typing import AsyncIterator

import httpx

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper

logger = logging.getLogger("tracker")


class AMDScraper(BaseScraper):
    """Scraper for AMD (careers.amd.com JSON API)."""

    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)
        self._api_base = "https://careers.amd.com/api/jobs"

    async def _fetch_pages(
        self, client: httpx.AsyncClient, extra_params: dict, seen: set
    ) -> AsyncIterator[RawJob]:
        page = 1
        while page <= 20:
            try:
                params = {
                    "page": page,
                    "sortBy": "relevance",
                    "descending": "false",
                    "internal": "false",
                    "location": "India",
                }
                params.update(extra_params)
                resp = await client.get(self._api_base, params=params)
                data = resp.json()
                jobs = data.get("jobs", [])
                if not jobs:
                    break

                for item in jobs:
                    d = item.get("data", {})
                    title = d.get("title", "").strip()
                    city = d.get("city", "")
                    country = d.get("country", "")
                    req_id = d.get("req_id", "")
                    location_name = d.get("location_name", "")

                    if not title:
                        continue

                    location = location_name or (f"{city}, {country}" if city else country)

                    uid = f"AMD|{req_id}"
                    if uid in seen:
                        continue
                    seen.add(uid)

                    job_url = (
                        f"https://careers.amd.com/careers-home/jobs/"
                        f"{d.get('slug', req_id)}?lang=en-us"
                    )

                    yield RawJob(
                        company="AMD",
                        title=title,
                        location=location,
                        url=job_url,
                        description=None,
                        employment_type=None,
                        date_posted=None,
                        source_ats="custom-api",
                    )

                page += 1
            except Exception as exc:
                logger.warning("AMD API error on page %d: %s", page, exc)
                break

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

            # General India jobs
            async for job in self._fetch_pages(client, {}, seen):
                yield job

            # Student / Intern / Temp India jobs
            async for job in self._fetch_pages(
                client,
                {"categories": "Student / Intern / Temp"},
                seen,
            ):
                yield job
