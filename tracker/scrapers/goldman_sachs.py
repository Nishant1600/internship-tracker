"""
Goldman Sachs scraper.

Uses the Higher API at api-higher.gs.com to fetch job listings.
Also checks the students programs page for internship opportunities.
"""

import asyncio
import logging
from typing import AsyncIterator

import httpx

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper

logger = logging.getLogger("tracker")

API_URL = "https://api-higher.gs.com/gateway/api/v1/graphql"

GET_ROLES_QUERY = """
query GetRoles($searchQueryInput: RoleSearchQueryInput!) {
  roleSearch(searchQueryInput: $searchQueryInput) {
    totalCount
    items {
      roleId
      corporateTitle
      jobTitle
      jobFunction
      locations {
        primary
        city
        state
        country
        __typename
      }
      status
      division
      jobType {
        code
        description
        __typename
      }
      __typename
    }
    __typename
  }
}
"""


class GoldmanSachsScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        try:
            async with httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Content-Type": "application/json",
                    "Origin": "https://higher.gs.com",
                    "Referer": "https://higher.gs.com/",
                },
            ) as client:
                page_num = 0
                page_size = 100
                seen = set()

                while True:
                    payload = {
                        "operationName": "GetRoles",
                        "variables": {
                            "searchQueryInput": {
                                "page": {"pageSize": page_size, "pageNumber": page_num},
                                "sort": {"sortStrategy": "RELEVANCE", "sortOrder": "DESC"},
                                "filters": [],
                                "experiences": ["EARLY_CAREER", "PROFESSIONAL"],
                                "searchTerm": "",
                            }
                        },
                        "query": GET_ROLES_QUERY,
                    }

                    resp = await client.post(API_URL, json=payload)
                    resp.raise_for_status()
                    data = resp.json()

                    rs = data.get("data", {}).get("roleSearch", {})
                    items = rs.get("items", [])

                    if not items:
                        break

                    for item in items:
                        locations = item.get("locations", [])
                        is_india = any(
                            "India" in (loc.get("country") or "")
                            for loc in locations
                        )
                        if not is_india:
                            continue

                        title = item.get("jobTitle", "")
                        if title in seen:
                            continue
                        seen.add(title)

                        loc_parts = []
                        for loc in locations:
                            if "India" in (loc.get("country") or ""):
                                city = loc.get("city", "")
                                if city:
                                    loc_parts.append(city)
                        location = ", ".join(loc_parts) if loc_parts else "India"

                        role_id = item.get("roleId", "")
                        url = f"https://higher.gs.com/results?id={role_id}" if role_id else "https://higher.gs.com/results"

                        yield RawJob(
                            company=self.company,
                            title=title,
                            location=location,
                            url=url,
                            description=None,
                            employment_type=None,
                            date_posted=None,
                            source_ats="goldmansachs",
                        )

                    page_num += 1
                    if len(items) < page_size:
                        break

        except Exception as e:
            logger.error("[GoldmanSachs] API scraping failed: %s", e)
