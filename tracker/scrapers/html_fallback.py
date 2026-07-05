"""
Generic HTML fallback scraper.

Uses Playwright to load a career page and extract job listings via a
configurable CSS selector from config.yaml.

This is inherently fragile — it depends on the page's DOM structure which
can change at any time. Documented as best-effort only.

NOTE: Playwright browser download required:
    playwright install chromium

If Playwright is not available, this scraper logs a warning and returns empty.
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


class HTMLFallbackScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)
        self._css_selector = company.css_selector or "div.job-listing"

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            self._log_warning("Playwright not installed. Install with: playwright install chromium")
            return

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=self.config.headless)
                page = await browser.new_page()
                await page.goto(self.url, timeout=self.config.timeout_seconds * 1000)
                await page.wait_for_load_state("networkidle")

                cards = await page.query_selector_all(self._css_selector)
                if not cards:
                    self._log_warning(
                        f"No elements matched CSS selector '{self._css_selector}' on {self.url}"
                    )
                    await browser.close()
                    return

                for card in cards:
                    parsed = await self._parse_card(card)
                    if parsed:
                        yield parsed

                await browser.close()
        except Exception as e:
            self._log_error(f"Playwright error on {self.url}: {e}")

    async def _parse_card(self, card) -> RawJob | None:
        title = await self._get_text(card, "h2, h3, .title, .job-title, [data-job-title]")
        if not title:
            return None

        location = await self._get_text(card, ".location, .job-location, [data-location]")
        url = await self._get_attr(card, "a", "href")
        description = await self._get_text(card, ".description, .job-description, .summary")
        employment_type = await self._get_text(card, ".type, .job-type, .employment-type")
        date_posted = await self._get_text(card, ".date, .posted-date, .job-date")

        if url and not url.startswith("http"):
            url = self.url.rstrip("/") + "/" + url.lstrip("/")

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=url or "",
            description=description,
            employment_type=employment_type,
            date_posted=date_posted,
            source_ats="html",
        )

    async def _get_text(self, card, selector: str) -> str | None:
        try:
            el = await card.query_selector(selector)
            if el:
                text = await el.inner_text()
                return text.strip() or None
        except Exception:
            pass
        return None

    async def _get_attr(self, card, selector: str, attr: str) -> str | None:
        try:
            el = await card.query_selector(selector)
            if el:
                val = await el.get_attribute(attr)
                return val.strip() if val else None
        except Exception:
            pass
        return None

    def _log_warning(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").warning("[HTMLFallback] %s", msg)

    def _log_error(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").error("[HTMLFallback] %s", msg)
