"""
LinkedIn Jobs scraper.

Scrapes company job listings from LinkedIn's public job search page.
URL pattern: https://www.linkedin.com/jobs/search/?f_C={company_id}&geoId=92000000

NOTE: LinkedIn may block automated access. Anti-detect settings are used.
"""

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


class LinkedInScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)
        self._company_id = getattr(company, "company_id", None) or ""

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("[LinkedIn] Playwright not installed")
            return

        url = self.url
        if not url and self._company_id:
            url = (
                f"https://www.linkedin.com/jobs/search/"
                f"?f_C={self._company_id}&geoId=92000000"
                f"&origin=COMPANY_PAGE_JOBS_CLUSTER_EXPANSION"
            )
        if not url:
            logger.warning("[LinkedIn] No URL or company_id for %s", self.company)
            return

        browser = None
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=self.config.headless,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                )
                page = await context.new_page()
                await page.goto(url, timeout=self.config.timeout_seconds * 1000)
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(3000)

                cards = await page.query_selector_all(
                    ".base-card, .job-search-card, li.jobs-search-results__list-item"
                )
                if not cards:
                    logger.warning(
                        "[LinkedIn] No job cards found for %s", self.company
                    )
                    return

                seen = set()
                total = 0
                for card in cards:
                    parsed = await self._parse_card(card)
                    if parsed:
                        key = (parsed.title, parsed.location or "")
                        if key not in seen:
                            seen.add(key)
                            total += 1
                            yield parsed

                logger.info("[LinkedIn] %s: %d unique jobs", self.company, total)
        except Exception as e:
            logger.error("[LinkedIn] Failed for %s: %s", self.company, e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def _parse_card(self, card) -> RawJob | None:
        title = await self._get_text(
            card, ".base-search-card__title, h3"
        )
        if not title:
            return None

        location = await self._get_text(card, ".job-search-card__location")

        url = None
        try:
            link = await card.query_selector("a.base-card__full-link")
            if link:
                url = await link.get_attribute("href")
        except Exception:
            pass
        if url:
            url = url.split("?")[0]

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=url or "",
            description=None,
            employment_type=None,
            date_posted=None,
            source_ats="linkedin",
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
