"""
American Express scraper.

Scrapes careers.americanexpress.com which uses a custom Knockout.js portal.
Loads jobs with India location filter, clicks "Show More" to load all pages.

REQUIRES: playwright install chromium
"""

import asyncio
from typing import AsyncIterator
from urllib.parse import urljoin

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class AmericanExpressScraper(BaseScraper):
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

                total_jobs = 0
                max_clicks = 50

                for _ in range(max_clicks):
                    cards = await page.query_selector_all(
                        "div.search-results.job-tile.job-list-item"
                    )

                    show_more = await page.query_selector(
                        "button:has-text('Show More')"
                    )
                    if not show_more:
                        break

                    is_hidden = await show_more.is_hidden()
                    is_disabled = await show_more.get_attribute("disabled")
                    if is_hidden or is_disabled is not None:
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

                cards = await page.query_selector_all(
                    "div.search-results.job-tile.job-list-item"
                )
                self._log_info(f"Found {len(cards)} total job cards")

                for card in cards:
                    parsed = await self._parse_card(card)
                    if parsed:
                        total_jobs += 1
                        yield parsed

                self._log_info(f"Total jobs scraped: {total_jobs}")
        except Exception as e:
            self._log_error(f"American Express scraping failed: {e}")
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def _parse_card(self, card) -> RawJob | None:
        title_el = await card.query_selector("span.job-tile__title")
        title = (await title_el.inner_text()).strip() if title_el else None

        if not title:
            return None

        link_el = await card.query_selector("a.job-list-item__link")
        url = await link_el.get_attribute("href") if link_el else None

        if url and not url.startswith("http"):
            url = urljoin("https://careers.americanexpress.com", url)

        location = None
        text = await card.inner_text()
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) > 1:
            loc_line = lines[1]
            loc_line = loc_line.split(" 0")[0].strip()
            location = loc_line if loc_line else None

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=url or "",
            description=None,
            employment_type=None,
            date_posted=None,
            source_ats="americanexpress",
        )

    def _log_warning(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").warning("[AmEx] %s", msg)

    def _log_error(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").error("[AmEx] %s", msg)

    def _log_info(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").info("[AmEx] %s", msg)
