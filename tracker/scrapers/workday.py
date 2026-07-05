"""
Workday scraper.

BEST-EFFORT ONLY. Workday career pages are tenant-specific and DOM
structures vary significantly between companies. The public API is
not consistently available.

This scraper attempts to use Playwright to load the career page and
extract job listings. It works for some Workday tenants but NOT all.

If the Playwright approach fails, the scraper returns empty — it
never crashes the pipeline.

REQUIRES: playwright install chromium
"""

from typing import AsyncIterator

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

WORKDAY_JOB_CARD_SELECTORS = [
    "li[data-automation-id='jobRow']",
    "div[data-automation-id='jobListing']",
    "div.job-listing",
    "tr[data-automation-id='jobRow']",
    "article[data-automation-id*='job']",
]


class WorkdayScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            self._log_warning("Playwright not installed (install: playwright install chromium)")
            return

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=self.config.headless)
                page = await browser.new_page()
                await page.goto(self.url, timeout=self.config.timeout_seconds * 1000)

                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass

                jobs_found = False
                for selector in WORKDAY_JOB_CARD_SELECTORS:
                    cards = await page.query_selector_all(selector)
                    if cards:
                        self._log_info(f"Found {len(cards)} job cards with selector '{selector}'")
                        for card in cards:
                            parsed = await self._parse_card(card)
                            if parsed:
                                yield parsed
                        jobs_found = True
                        break

                if not jobs_found:
                    body_text = await page.inner_text("body")
                    lines = [l.strip() for l in body_text.split("\n") if l.strip()]
                    self._log_warning(
                        f"No job cards found on {self.url}. "
                        f"Page loaded but no known selectors matched. "
                        f"Page has {len(lines)} lines of text."
                    )

                await browser.close()
        except Exception as e:
            self._log_error(f"Workday scraping failed for {self.url}: {e}")

    async def _parse_card(self, card) -> RawJob | None:
        title_el = await card.query_selector(
            "a[data-automation-id='jobTitle'], "
            "a.job-title, "
            "h3 a, h2 a, "
            "[data-automation-id*='title'] a"
        )
        title = None
        url = None
        if title_el:
            title = (await title_el.inner_text()).strip()
            url = await title_el.get_attribute("href")
        if not title:
            title_text = await card.inner_text()
            lines = [l.strip() for l in title_text.split("\n") if l.strip()]
            title = lines[0] if lines else None

        if not title:
            return None

        location = None
        loc_el = await card.query_selector(
            "[data-automation-id='jobLocation'], "
            ".job-location, "
            "[data-automation-id*='location']"
        )
        if loc_el:
            location = (await loc_el.inner_text()).strip() or None

        if url and not url.startswith("http"):
            base = self.url.rstrip("/")
            url = base + "/" + url.lstrip("/")

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=url or "",
            description=None,
            employment_type=None,
            date_posted=None,
            source_ats="workday",
        )

    def _log_warning(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").warning("[Workday] %s", msg)

    def _log_error(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").error("[Workday] %s", msg)

    def _log_info(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").info("[Workday] %s", msg)
