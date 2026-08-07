"""
Netflix Careers scraper.

Uses Netflix's public API to fetch all job listings.
API: https://explore.jobs.netflix.net/api/apply/v2/jobs?domain=netflix.com&start=N
"""

import logging
from typing import AsyncIterator

import httpx

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper

logger = logging.getLogger("tracker")

NETFLIX_API = "https://explore.jobs.netflix.net/api/apply/v2/jobs"
PAGE_SIZE = 10
MAX_PAGES = 100


class NetflixScraper(BaseScraper):
    """Scrape Netflix Careers using their public API."""

    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        try:
            async with httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
            ) as client:
                seen = set()
                total_scraped = 0

                for page_num in range(MAX_PAGES):
                    start = page_num * PAGE_SIZE
                    resp = await client.get(
                        NETFLIX_API,
                        params={"domain": "netflix.com", "start": start},
                    )
                    if resp.status_code != 200:
                        logger.warning("[Netflix] API returned %d at start=%d", resp.status_code, start)
                        break

                    data = resp.json()
                    positions = data.get("positions", [])
                    total_count = data.get("count", 0)

                    if not positions:
                        break

                    for pos in positions:
                        title = pos.get("name", "").strip()
                        location = pos.get("location", "").strip()
                        job_id = pos.get("id")

                        if not title or job_id in seen:
                            continue
                        seen.add(job_id)

                        url = f"https://explore.jobs.netflix.net/careers/{job_id}"
                        if location:
                            # Clean location format: "City,State,Country" -> "City, State, Country"
                            location = location.replace(",", ", ")

                        total_scraped += 1
                        yield RawJob(
                            company=self.company,
                            title=title,
                            location=location or None,
                            url=url,
                            description=None,
                            employment_type=None,
                            date_posted=None,
                            source_ats="netflix",
                        )

                    logger.info("[Netflix] Page %d: %d jobs (total: %d/%d)", page_num + 1, len(positions), total_scraped, total_count)

                    if start + PAGE_SIZE >= total_count:
                        break

                logger.info("[Netflix] Total jobs scraped: %d", total_scraped)

        except Exception as e:
            logger.error("[Netflix] Failed for %s: %s", self.url, e)
