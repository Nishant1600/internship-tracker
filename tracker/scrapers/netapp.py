"""
NetApp scraper.

NetApp uses SuccessFactors for their careers site.
Jobs are paginated with 18 per page, 6 pages total for India.
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


class NetAppScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("[NetApp] Playwright not installed")
            return

        base_url = "https://careers.netapp.com/search-jobs/India/27600"

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

                seen = set()
                max_pages = 10

                for page_num in range(1, max_pages + 1):
                    url = f"{base_url}/{page_num}"
                    await page.goto(url, timeout=30000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        pass

                    await asyncio.sleep(2)

                    links = await page.query_selector_all('a[href*="/job/"]')
                    if not links:
                        break

                    for link in links:
                        text = (await link.inner_text()).strip()
                        if not text:
                            continue

                        lines = [l.strip() for l in text.split("\n") if l.strip()]
                        if len(lines) < 1:
                            continue

                        title = lines[0]
                        location = lines[1] if len(lines) > 1 else None
                        if location and len(location) > 100:
                            location = None

                        href = await link.get_attribute("href") or ""
                        if not href.startswith("http"):
                            href = f"https://careers.netapp.com{href}"

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
                            source_ats="netapp",
                        )

                    next_btn = await page.query_selector('a:has-text("Next")')
                    if not next_btn:
                        break

                    is_disabled = await next_btn.get_attribute("class")
                    if is_disabled and "disabled" in str(is_disabled):
                        break

        except Exception as e:
            logger.error("[NetApp] Scraping failed: %s", e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
