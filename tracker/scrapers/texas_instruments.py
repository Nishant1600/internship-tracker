"""
Texas Instruments scraper.

TI uses a custom careers site at careers.ti.com with infinite scroll.
Jobs are loaded in batches of 25 as the page scrolls down.
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


class TexasInstrumentsScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("[TexasInstruments] Playwright not installed")
            return

        search_url = self.url
        if "?" in search_url:
            search_url += "&location=India"
        else:
            search_url += "?location=India"

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

                await asyncio.sleep(3)

                seen = set()
                prev_count = 0
                max_scrolls = 20

                for _ in range(max_scrolls):
                    items = await page.query_selector_all(
                        '[class*="job-list-item"]'
                    )
                    current_count = len(items)

                    if current_count == prev_count:
                        break

                    for item in items[prev_count:current_count]:
                        text = (await item.inner_text()).strip()
                        if not text:
                            continue
                        lines = [l.strip() for l in text.split("\n") if l.strip()]
                        if len(lines) < 2:
                            continue

                        title = lines[0]
                        location_line = lines[1]

                        location = location_line.split("POSTING DATE")[0].strip()
                        if not location:
                            location = None

                        link = await item.query_selector('a[href*="/job/"]')
                        href = ""
                        if link:
                            href = await link.get_attribute("href") or ""

                        if title in seen:
                            continue
                        seen.add(title)

                        yield RawJob(
                            company=self.company,
                            title=title,
                            location=location,
                            url=href,
                            description=None,
                            employment_type=None,
                            date_posted=None,
                            source_ats="texasinstruments",
                        )

                    prev_count = current_count
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(2)

        except Exception as e:
            logger.error("[TexasInstruments] Scraping failed: %s", e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
