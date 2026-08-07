"""
Eightfold AI scraper.

Generic scraper for companies using the Eightfold AI careers platform.
Used by PayPal, Morgan Stanley (when configured as 'eightfold'), etc.
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


class EightfoldScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("[Eightfold] Playwright not installed for %s", self.company)
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

                # Get all job links
                links = await page.query_selector_all("a[href*='job']")
                seen = set()
                for link in links:
                    text = (await link.inner_text()).strip()
                    href = await link.get_attribute("href")

                    if not text or not href:
                        continue

                    # Parse title and location from combined text
                    lines = [l.strip() for l in text.split("\n") if l.strip()]
                    if len(lines) < 2:
                        continue

                    title = lines[0]
                    location = lines[1] if len(lines) > 1 else ""

                    key = f"{title}|{location}"
                    if key in seen:
                        continue
                    seen.add(key)

                    # Build full URL
                    url = href
                    if not url.startswith("http"):
                        from urllib.parse import urlparse
                        parsed = urlparse(self.url)
                        url = f"{parsed.scheme}://{parsed.netloc}{href}"

                    yield RawJob(
                        company=self.company,
                        title=title,
                        location=location,
                        url=url,
                        description=None,
                        employment_type=None,
                        date_posted=None,
                        source_ats="eightfold",
                    )

        except Exception as e:
            logger.error("[Eightfold] Failed for %s: %s", self.company, e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass


# Keep backward compatibility
PayPalScraper = EightfoldScraper
