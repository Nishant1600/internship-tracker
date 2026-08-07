"""
Cisco careers scraper.

Cisco uses PhenomPeople but with a custom search-results page that
renders 10 jobs per page with pagination. This scraper paginates
through all pages to collect all jobs.
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


class CiscoScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("[Cisco] Playwright not installed")
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

                await page.goto(self.url, timeout=30000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass

                await asyncio.sleep(3)

                seen = set()
                page_num = 0
                max_pages = 100

                while page_num < max_pages:
                    page_num += 1
                    cards = await page.query_selector_all('a[href*="/job/"]')

                    if not cards:
                        break

                    for card in cards:
                        href = await card.get_attribute("href")
                        if not href or href in seen:
                            continue
                        seen.add(href)

                        job = await self._parse_card(card, href)
                        if job:
                            yield job

                    next_btn = await page.query_selector(
                        'button:has-text("Next"), a:has-text("Next")'
                    )
                    if not next_btn:
                        break

                    is_disabled = await next_btn.get_attribute("disabled")
                    if is_disabled is not None:
                        break

                    try:
                        await next_btn.click(timeout=5000)
                    except Exception:
                        break
                    await asyncio.sleep(2)

                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass

        except Exception as e:
            logger.error("[Cisco] Scraping failed: %s", e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def _parse_card(self, card, href: str) -> RawJob | None:
        title = (await card.inner_text()).strip()
        if not title:
            return None

        location = None
        try:
            parent = await card.evaluate_handle(
                "el => el.closest('div[data-ps]')?.parentElement || el.parentElement"
            )
            if parent:
                full_text = await parent.inner_text()
                lines = [l.strip() for l in full_text.split("\n") if l.strip()]
                for i, line in enumerate(lines[1:], 1):
                    if line == "Location:" and i + 1 < len(lines):
                        location = lines[i + 1]
                        break
                    elif "Available in" in line and "location" in line.lower():
                        location = None
                        break
        except Exception:
            pass

        if not href.startswith("http"):
            href = f"https://careers.cisco.com{href}"

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=href,
            description=None,
            employment_type=None,
            date_posted=None,
            source_ats="cisco",
        )
