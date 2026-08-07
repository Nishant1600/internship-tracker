"""
SuccessFactors scraper.

SAP SuccessFactors career pages are tenant-specific. This scraper
uses Playwright to load the page and try common CSS selectors.

BEST-EFFORT ONLY — some SuccessFactors pages may not work.
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

SF_SELECTORS = [
    "li:has(a[href*='/job/'])",
    "table tr:has(a[href*='/job/'])",
    "li.job-item",
    "div.job-item",
    "article.job-item",
    "div[datajobid]",
    "li[data-automation-id='jobRow']",
    "div.job-listing",
    "tr.job-row",
    ".job-card",
]


class SuccessFactorsScraper(BaseScraper):
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
                await page.goto(
                    self.url,
                    timeout=self.config.timeout_seconds * 1000,
                    wait_until="commit",
                )
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass

                for selector in SF_SELECTORS:
                    cards = await page.query_selector_all(selector)
                    if cards:
                        self._log_info(f"Found {len(cards)} jobs with '{selector}'")
                        for card in cards:
                            job = await self._parse_card(card)
                            if job:
                                yield job
                        break
                else:
                    # JS-rendered pages may need extra wait
                    try:
                        await page.wait_for_selector(
                            "a[href*='/job/'], tr[data-row], [class*='result']",
                            timeout=10000,
                        )
                        await asyncio.sleep(2)
                    except Exception:
                        pass

                    for selector in SF_SELECTORS:
                        cards = await page.query_selector_all(selector)
                        if cards:
                            self._log_info(f"Found {len(cards)} jobs with '{selector}'")
                            for card in cards:
                                job = await self._parse_card(card)
                                if job:
                                    yield job
                            break
                    else:
                        self._log_warning(f"No job cards found on {self.url}")

        except Exception as e:
            self._log_error(f"Scraping failed for {self.url}: {e}")
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def _parse_card(self, card) -> RawJob | None:
        title_el = await card.query_selector(
            "a[data-automation-id='jobTitle'], "
            "a.job-title, h2 a, h3 a, "
            "[data-automation-id*='title'] a, "
            ".job-title a, .job-card-title a"
        )
        title = None
        url = None
        if title_el:
            title = (await title_el.inner_text()).strip()
            url = await title_el.get_attribute("href")
        if not title:
            text = (await card.inner_text()).strip()
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            title = lines[0] if lines else None

        if not title:
            return None

        location = None
        loc_el = await card.query_selector(
            "[data-automation-id='jobLocation'], "
            ".job-location, [data-automation-id*='location'], "
            "[class*='jobCardLocation'], [class*='location'], "
            "td:nth-child(2)"
        )
        if loc_el:
            location = (await loc_el.inner_text()).strip() or None

        if not location:
            text = (await card.inner_text()).strip()
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            if len(lines) >= 3:
                location = ", ".join(lines[2:])
            elif len(lines) >= 2:
                location = lines[1]

        if url and not url.startswith("http"):
            url = self.url.rstrip("/") + "/" + url.lstrip("/")

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=url or "",
            description=None,
            employment_type=None,
            date_posted=None,
            source_ats="successfactors",
        )

    def _log_warning(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").warning("[SuccessFactors] %s", msg)

    def _log_error(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").error("[SuccessFactors] %s", msg)

    def _log_info(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").info("[SuccessFactors] %s", msg)
