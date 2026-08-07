"""
TCS iBegin scraper.

TCS uses an AngularJS-based career page where job cards are rendered as
div.searched-job elements.  Titles are stored in a tooltip attribute
(data-uib-tooltip) rather than visible text, and there are no direct
href links — navigation is handled via ng-click.
"""

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

_BASE_URL = "https://ibegin.tcsapps.com/candidate/jobs/search"


class TCSScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("[TCS] Playwright not installed. Skipping.")
            return

        browser = None
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=self.config.headless)
                page = await browser.new_page()
                await page.goto(self.url, timeout=self.config.timeout_seconds * 1000)
                await page.wait_for_load_state("networkidle")

                cards = await page.query_selector_all(".searched-job")
                if not cards:
                    logger.warning("[TCS] No .searched-job elements found on %s", self.url)
                    return

                logger.info("[TCS] Found %d jobs", len(cards))
                for card in cards:
                    job = await self._parse_card(card)
                    if job:
                        yield job

        except Exception as e:
            logger.error("[TCS] Playwright error on %s: %s", self.url, e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def _parse_card(self, card) -> RawJob | None:
        # Title is in the tooltip attribute of the <a> tag
        title = None
        link = await card.query_selector("a.hand")
        if link:
            title = await link.get_attribute("data-uib-tooltip")

        if not title:
            # Fallback: first .job-info-title span text
            span = await card.query_selector(".job-info-title span.ng-binding")
            if span:
                title = await span.inner_text()

        if not title or not title.strip():
            return None
        title = title.strip()

        # Extract location and description from the text lines
        info_divs = await card.query_selector_all(".job-info")
        texts = []
        for div in info_divs:
            t = await div.inner_text()
            t = t.strip()
            if t:
                texts.append(t)

        # Structure: [title_short, location, function, experience, date]
        location = texts[1] if len(texts) > 1 else None
        description = texts[2] if len(texts) > 2 else None

        # No direct URL — TCS uses Angular routing via ng-click
        job_id = None
        if link:
            href = await link.get_attribute("href")
            if href:
                job_id = href

        url = ""
        if job_id:
            url = f"{self.url}?jobId={job_id}"

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=url,
            description=description,
            employment_type=None,
            date_posted=texts[4] if len(texts) > 4 else None,
            source_ats="html",
        )
