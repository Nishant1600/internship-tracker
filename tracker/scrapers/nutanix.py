"""
Nutanix scraper.

Nutanix uses Jobvite for their careers site at careers.nutanix.com.
Jobs are filtered by India using URL parameters.
"""

import asyncio
import logging
from typing import AsyncIterator

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper

logger = logging.getLogger("tracker")

try:
    from playwright.async_api import async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class NutanixScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("[Nutanix] Playwright not installed")
            return

        search_url = "https://careers.nutanix.com/en/jobs/?orderby=0&pagesize=20&page=1&radius=100&country=India"

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

                await page.goto(search_url, timeout=30000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass

                await asyncio.sleep(5)

                content = await page.inner_text("body")
                lines = [l.strip() for l in content.split("\n") if l.strip()]

                seen = set()
                i = 0
                while i < len(lines):
                    line = lines[i]
                    if any(x in line for x in ["India", "Bangalore", "Pune", "Mumbai", "Remote"]):
                        if i > 0:
                            title = lines[i - 1]
                            location = line
                            if title not in seen and len(title) > 5:
                                seen.add(title)
                                href = f"https://careers.nutanix.com/en/jobs/"
                                yield RawJob(
                                    company=self.company,
                                    title=title,
                                    location=location,
                                    url=href,
                                    description=None,
                                    employment_type=None,
                                    date_posted=None,
                                    source_ats="nutanix",
                                )
                    i += 1

        except Exception as e:
            logger.error("[Nutanix] Scraping failed: %s", e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
