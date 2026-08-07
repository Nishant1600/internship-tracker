"""
Morgan Stanley scraper.

Uses the Eightfold AI careers platform at morganstanley.eightfold.ai.
Scrapes job listings by intercepting the page content.
"""

import asyncio
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


class MorganStanleyScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("[MorganStanley] Playwright not installed for %s", self.company)
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
                await page.goto(self.url, timeout=self.config.timeout_seconds * 1000)

                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass

                await asyncio.sleep(3)

                # Get all job links
                links = await page.query_selector_all("a[href*='job']")
                seen = set()
                for link in links:
                    text = (await link.inner_text()).strip()
                    href = await link.get_attribute("href")

                    if not text or not href:
                        continue

                    # Parse title and location from combined text
                    lines = [l.strip() for l in text.split("\n") if l.strip()]
                    if len(lines) < 2:
                        continue

                    title = lines[0]
                    location = lines[1] if len(lines) > 1 else ""

                    if title in seen:
                        continue
                    seen.add(title)

                    # Build full URL
                    url = href
                    if not url.startswith("http"):
                        url = f"https://morganstanley.eightfold.ai{href}"

                    yield RawJob(
                        company=self.company,
                        title=title,
                        location=location,
                        url=url,
                        description=None,
                        employment_type=None,
                        date_posted=None,
                        source_ats="eightfold",
                    )

        except Exception as e:
            logger.error("[MorganStanley] Failed for %s: %s", self.company, e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
