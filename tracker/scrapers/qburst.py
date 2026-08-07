"""
QBurst custom scraper.

Intercepts the CMS API (cms.qburst.com/api/jobs) via Playwright route
modification to fetch all jobs in a single request (pageSize=100).
"""

import logging
import re
from typing import AsyncIterator

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

logger = logging.getLogger("tracker")


class QBurstScraper(BaseScraper):
    """Intercept QBurst CMS API to get all jobs."""

    def __init__(self, company: CompanyConfig, config: ScraperConfig):
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.error("[QBurst] Playwright not installed")
            return

        browser = None
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=self.config.headless,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = await context.new_page()

                async def route_handler(route):
                    url = route.request.url
                    if "cms.qburst.com/api/jobs" in url:
                        url = re.sub(r"pagination%5BpageSize%5D=\d+", "pagination%5BpageSize%5D=100", url)
                        url = re.sub(r"pagination\[pageSize\]=\d+", "pagination[pageSize]=100", url)
                    await route.continue_(url=url)

                await page.route("**/*", route_handler)

                api_data = []

                async def handle_response(response):
                    if "cms.qburst.com/api/jobs" in response.url:
                        try:
                            data = await response.json()
                            api_data.append(data)
                        except Exception:
                            pass

                page.on("response", handle_response)

                await page.goto(self.url, timeout=self.config.timeout_seconds * 1000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass

                if not api_data:
                    logger.error("[QBurst] No API data captured")
                    return

                total = api_data[0].get("meta", {}).get("pagination", {}).get("total", 0)
                logger.info("[QBurst] Captured %d jobs from API", total)

                seen = set()
                for data in api_data:
                    for job in data.get("data", []):
                        attrs = job.get("attributes", job)
                        title = attrs.get("job_title", "")
                        location = attrs.get("location_text", "")
                        code = attrs.get("job_code", "")
                        desc = attrs.get("job_description", "")

                        if not title or title in seen:
                            continue
                        seen.add(title)

                        job_id = str(job.get("id", code))
                        url = f"https://www.qburst.com/en-in/company/career/openings/?job={code}" if code else self.url

                        yield RawJob(
                            company=self.company,
                            title=title.strip(),
                            url=url,
                            location=location.strip() if location else None,
                            description=desc.strip() if desc else None,
                            employment_type=None,
                            date_posted=None,
                            source_ats="qburst",
                        )

                logger.info("[QBurst] Yielded %d unique jobs", len(seen))

        except Exception as e:
            logger.error("[QBurst] Failed: %s", e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
