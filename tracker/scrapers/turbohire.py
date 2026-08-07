"""
Turbohire ATS scraper.

Used by Navi and other companies that use Turbohire (thapi.azurewebsites.net)
for their careers page. The API requires a two-step process:
1. GET token from /api/token/noauth (with Referer header)
2. POST to /api/careerpagev2/filteredjobs with Bearer token
"""

import json
import logging
from typing import AsyncIterator, Any

import httpx

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper

logger = logging.getLogger("tracker")


class TurbohireScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)
        self._org_id = getattr(company, "org_id", None) or ""

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not self._org_id:
            logger.warning("[Turbohire] No org_id for %s", self.company)
            return

        base_url = "https://thapi.azurewebsites.net"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://navi.turbohire.co/",
        }

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            try:
                # Step 1: Get token
                token_resp = await client.get(f"{base_url}/api/token/noauth", headers=headers)
                if token_resp.status_code != 200:
                    logger.warning("[Turbohire] Token failed for %s: %d", self.company, token_resp.status_code)
                    return
                token = token_resp.json().get("access_token", "")
                if not token:
                    logger.warning("[Turbohire] No token for %s", self.company)
                    return

                # Step 2: Get jobs
                auth_headers = {
                    **headers,
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }
                resp = await client.post(
                    f"{base_url}/api/careerpagev2/filteredjobs",
                    params={"orgId": self._org_id, "pageType": 0},
                    headers=auth_headers,
                    json={
                        "SortByV2": {"Key": "PostedDate", "Order": 2},
                        "Keyword": "",
                        "Department": "",
                        "CustomFields": {},
                    },
                )
                if resp.status_code != 200:
                    logger.warning("[Turbohire] Jobs failed for %s: %d", self.company, resp.status_code)
                    return

                data = resp.json()
                jobs_raw = data.get("Result", [])
                if not jobs_raw:
                    logger.warning("[Turbohire] No jobs found for %s", self.company)
                    return

                for item in jobs_raw:
                    parsed = self._parse_job(item)
                    if parsed:
                        yield parsed

                logger.info("[Turbohire] %s: %d jobs", self.company, len(jobs_raw))

            except Exception as e:
                logger.error("[Turbohire] Failed for %s: %s", self.company, e)

    def _parse_job(self, item: dict) -> RawJob | None:
        title = (item.get("JobTitle") or "").strip()
        if not title:
            return None

        location = item.get("Location", "")
        if isinstance(location, str) and location.startswith("["):
            try:
                locs = json.loads(location)
                location = locs[0].get("Address", "") if locs else ""
            except (json.JSONDecodeError, IndexError):
                pass
        if not location:
            location = None

        job_code = item.get("JobCode", "")
        job_id = item.get("JobIdObfuscated", "")
        url = f"https://navi.turbohire.co/jobs/{job_id}" if job_id else ""

        description = (item.get("JobDescription") or "").strip() or None

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=url,
            description=description,
            employment_type=None,
            date_posted=item.get("PublishedDate"),
            source_ats="turbohire",
        )
