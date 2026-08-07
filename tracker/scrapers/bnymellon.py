"""
BNY Mellon scraper.

Scrapes eofe.fa.us2.oraclecloud.com Oracle HCM Candidate Experience.
Loads India jobs with infinite scroll to fetch all listings.

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


class BNYMellonScraper(BaseScraper):
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
                    await page.wait_for_load_state("networkidle", timeout=30000)
                except Exception:
                    pass
                await asyncio.sleep(5)

                prev_count = 0
                max_scrolls = 200
                for i in range(max_scrolls):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(1.5)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass

                    body = await page.inner_text("body")
                    count = sum(1 for l in body.split("\n") if "POSTING DATE" in l)
                    if count == prev_count and i > 10:
                        break
                    prev_count = count

                body = await page.inner_text("body")
                lines = [l.strip() for l in body.split("\n") if l.strip()]

                total_jobs = 0
                i = 0
                while i < len(lines):
                    line = lines[i]
                    if (
                        "india" in line.lower()
                        and i > 0
                        and "posting date" in line.lower()
                    ):
                        location = line.split("POSTING DATE")[0].strip()
                        title = lines[i - 1]

                        url = None
                        try:
                            link = await page.query_selector(f'a:has-text("{title[:50]}")')
                            if link:
                                url = await link.get_attribute("href")
                        except Exception:
                            pass

                        if url and not url.startswith("http"):
                            url = "https://eofe.fa.us2.oraclecloud.com" + url

                        total_jobs += 1
                        yield RawJob(
                            company=self.company,
                            title=title,
                            location=location,
                            url=url or "",
                            description=None,
                            employment_type=None,
                            date_posted=None,
                            source_ats="bnymellon",
                        )
                    i += 1

                self._log_info(f"Total India jobs scraped: {total_jobs}")
        except Exception as e:
            self._log_error(f"BNY Mellon scraping failed: {e}")
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    def _log_warning(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").warning("[BNY] %s", msg)

    def _log_error(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").error("[BNY] %s", msg)

    def _log_info(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").info("[BNY] %s", msg)
