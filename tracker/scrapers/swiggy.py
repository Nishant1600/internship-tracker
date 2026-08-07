"""
Swiggy custom scraper.

Intercepts the NextHire API (swiggy.mynexthire.com) via Playwright to fetch
all jobs from the careers page.
"""

import logging
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


class SwiggyScraper(BaseScraper):
    """Intercept Swiggy NextHire API to get all jobs."""

    def __init__(self, company: CompanyConfig, config: ScraperConfig):
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.error("[Swiggy] Playwright not installed")
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

                api_data = []

                async def handle_response(response):
                    if "reqlist" in response.url and response.status == 200:
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

                selects = await page.query_selector_all("select")
                if selects:
                    await selects[0].select_option("Technology")
                    await page.wait_for_timeout(2000)
                    if len(selects) > 1:
                        await selects[1].select_option("Bengaluru")
                        await page.wait_for_timeout(3000)

                if not api_data:
                    logger.error("[Swiggy] No API data captured")
                    return

                all_jobs = []
                for data in api_data:
                    all_jobs.extend(data.get("reqDetailsBOList", []))

                logger.info("[Swiggy] Captured %d jobs from API", len(all_jobs))

                seen = set()
                for job in all_jobs:
                    title = job.get("reqTitle", "")
                    location = job.get("location", "")
                    req_id = job.get("reqId", "")

                    if not title or title in seen:
                        continue
                    seen.add(title)

                    url = f"https://careers.swiggy.com/#/careers" if req_id else self.url

                    yield RawJob(
                        company=self.company,
                        title=title.strip(),
                        url=url,
                        location=location.strip() if location else None,
                        description=None,
                        employment_type=None,
                        date_posted=None,
                        source_ats="swiggy",
                    )

                logger.info("[Swiggy] Yielded %d unique jobs", len(seen))

        except Exception as e:
            logger.error("[Swiggy] Failed: %s", e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
