"""
HSBC scraper.

Scrapes portal.careers.hsbc.com which uses Eightfold AI.
Loads jobs with India location filter, clicks "Show more" to load all.

REQUIRES: playwright install chromium
"""

import asyncio
from typing import AsyncIterator

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class HSBCScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            self._log_warning("Playwright not installed")
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

                max_clicks = 50
                for _ in range(max_clicks):
                    show_more = await page.query_selector(
                        "button.show-more-positions, button:has-text('Show more')"
                    )
                    if not show_more:
                        break
                    is_hidden = await show_more.is_hidden()
                    if is_hidden:
                        break
                    try:
                        await show_more.click()
                        await asyncio.sleep(2)
                        try:
                            await page.wait_for_load_state(
                                "networkidle", timeout=10000
                            )
                        except Exception:
                            pass
                        await asyncio.sleep(1)
                    except Exception:
                        break

                cards = await page.query_selector_all(".job-card-container")
                self._log_info(f"Found {len(cards)} job cards")

                total_jobs = 0
                for card in cards:
                    parsed = await self._parse_card(card)
                    if parsed:
                        total_jobs += 1
                        yield parsed

                self._log_info(f"Total jobs scraped: {total_jobs}")
        except Exception as e:
            self._log_error(f"HSBC scraping failed: {e}")
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def _parse_card(self, card) -> RawJob | None:
        title_el = await card.query_selector("h3.job-card-title, h3")
        title = (await title_el.inner_text()).strip() if title_el else None

        if not title:
            return None

        location = None
        text = await card.inner_text()
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) > 1:
            for line in lines[1:4]:
                if any(
                    x in line.lower()
                    for x in ["india", "bengaluru", "pune", "mumbai", "hyderabad"]
                ):
                    location = line
                    break
            if not location and len(lines) > 1:
                location = lines[1]

        link_el = await card.query_selector("a[href*='/job/']")
        url = await link_el.get_attribute("href") if link_el else None
        if url and not url.startswith("http"):
            url = "https://portal.careers.hsbc.com" + url

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=url or "",
            description=None,
            employment_type=None,
            date_posted=None,
            source_ats="hsbc",
        )

    def _log_warning(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").warning("[HSBC] %s", msg)

    def _log_error(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").error("[HSBC] %s", msg)

    def _log_info(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").info("[HSBC] %s", msg)
