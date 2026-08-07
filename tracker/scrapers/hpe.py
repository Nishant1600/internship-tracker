"""
HPE/Juniper PhenomPeople API scraper.

Uses the HPE careers PhenomPeople widget API to search for jobs
with keyword and location filters. Simple httpx POST calls.
"""

import logging
from typing import AsyncIterator

import httpx

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper

logger = logging.getLogger("tracker")


class HPEScraper(BaseScraper):
    """Scraper for HPE/Juniper (PhenomPeople widget API)."""

    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)
        self._api_url = "https://careers.hpe.com/widgets"

    def _extract_keyword(self) -> str:
        """Extract keyword from URL query params."""
        if "keywords=" in self.url:
            return self.url.split("keywords=")[1].split("&")[0]
        return ""

    async def fetch(self) -> AsyncIterator[RawJob]:
        keyword = self._extract_keyword()
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
                "Content-Type": "application/json",
            },
        ) as client:
            seen: set[str] = set()
            offset = 0
            while offset < 500:
                try:
                    payload = {
                        "lang": "en_us",
                        "deviceType": "desktop",
                        "country": "us",
                        "pageName": "search-results",
                        "ddoKey": "refineSearch",
                        "sortBy": "",
                        "subs498": "",
                        "from": offset,
                        "jobs": True,
                        "counts": True,
                        "all_fields": ["category", "country", "state", "city", "type", "subCategory"],
                        "size": 100,
                        "clear498": False,
                        "jdsource": "facets",
                        "is498": True,
                        "global": True,
                        "selected_fields": {"location": [], "country": ["India"]},
                        "keyword": keyword,
                    }
                    resp = await client.post(self._api_url, json=payload)
                    data = resp.json()
                    rs = data.get("refineSearch", {})
                    d = rs.get("data", {})
                    jobs = d.get("jobs", [])
                    if not jobs:
                        break

                    for j in jobs:
                        title = j.get("title", "").strip()
                        city = j.get("city", "")
                        country = j.get("country", "")
                        location = f"{city}, {country}" if city else country
                        job_id = j.get("jobId", "") or j.get("reqId", "")

                        if not title:
                            continue

                        uid = f"{self.company}|{job_id or title}"
                        if uid in seen:
                            continue
                        seen.add(uid)

                        job_url = j.get("url") or j.get("applyUrl") or self.url

                        yield RawJob(
                            company=self.company,
                            title=title,
                            location=location,
                            url=job_url,
                            description=None,
                            employment_type=j.get("type"),
                            date_posted=j.get("postedDate"),
                            source_ats="hpe",
                        )

                    offset += 100
                    if offset >= d.get("totalHits", rs.get("totalHits", 0)):
                        break
                except Exception as exc:
                    logger.warning("HPE API error at offset %d: %s", offset, exc)
                    break
