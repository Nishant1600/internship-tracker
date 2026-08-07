"""
Notion Careers scraper.

Uses Playwright to scrape Notion's career site.
Extracts job listings from the careers page (uses Ashby job board links).

REQUIRES: playwright install chromium
"""

import asyncio
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


class NotionScraper(BaseScraper):
    """Scrape Notion Careers using Playwright."""

    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("[Notion] Playwright not installed (install: playwright install chromium)")
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
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                await asyncio.sleep(3)

                # Extract Ashby job links
                links = await page.query_selector_all("a[href*='jobs.ashbyhq.com/notion/']")
                seen = set()
                total_scraped = 0

                for link in links:
                    try:
                        text = (await link.inner_text()).strip()
                        href = await link.get_attribute("href") or ""

                        if not text or len(text) < 5 or len(text) > 200:
                            continue

                        # Skip non-job links
                        if text in seen or "Get Notion" in text or "Log in" in text:
                            continue

                        # Parse job info from link text
                        # Format: "Title\\nLocation" or "Title\\nLocation1; Location2"
                        lines = [l.strip() for l in text.split("\n") if l.strip()]
                        if len(lines) < 1:
                            continue

                        title = lines[0]
                        location = lines[1] if len(lines) >= 2 else None

                        # Clean up location
                        if location:
                            # Remove "See posting" or similar suffixes
                            location = re.sub(r'\s*See posting.*$', '', location, flags=re.IGNORECASE)
                            location = location.strip() or None

                        key = (title, location or "")
                        if key in seen:
                            continue
                        seen.add(key)

                        total_scraped += 1
                        yield RawJob(
                            company=self.company,
                            title=title,
                            location=location,
                            url=href,
                            description=None,
                            employment_type=None,
                            date_posted=None,
                            source_ats="notion",
                        )
                    except Exception:
                        continue

                logger.info("[Notion] Total jobs scraped: %d", total_scraped)

        except Exception as e:
            logger.error("[Notion] Scraping failed for %s: %s", self.url, e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
