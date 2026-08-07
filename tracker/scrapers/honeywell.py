"""
Honeywell scraper.

Honeywell uses Oracle HCM Cloud for their careers site.
Jobs are paginated with 25 per page.
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


class HoneywellScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("[Honeywell] Playwright not installed")
            return

        search_url = "https://ibqbjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/Honeywell/jobs?location=India&locationId=300000000469485&locationLevel=country&mode=location"

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

                await asyncio.sleep(5)

                seen = set()
                prev_count = 0
                max_scrolls = 15

                for _ in range(max_scrolls):
                    links = await page.query_selector_all(
                        'a.job-list-item__link'
                    )
                    current_count = len(links)

                    if current_count == prev_count:
                        break

                    for link in links[prev_count:current_count]:
                        href = await link.get_attribute("href") or ""
                        if not href.startswith("http"):
                            href = f"https://ibqbjb.fa.ocs.oraclecloud.com{href}"

                        sibling = await link.evaluate_handle(
                            "el => el.nextElementSibling"
                        )
                        if not sibling:
                            continue

                        text = (await sibling.inner_text()).strip()
                        if not text:
                            continue

                        lines = [l.strip() for l in text.split("\n") if l.strip()]
                        if len(lines) < 1:
                            continue

                        title = lines[0]
                        location = lines[1] if len(lines) > 1 else None
                        if location:
                            import re
                            location = re.sub(r"POSTING DATE.*", "", location).strip()

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
                            source_ats="honeywell",
                        )

                    prev_count = current_count
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(2)

        except Exception as e:
            logger.error("[Honeywell] Scraping failed: %s", e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
