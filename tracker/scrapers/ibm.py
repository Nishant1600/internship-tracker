"""
IBM scraper.

Intercepts the IBM search API via Playwright.
The API is called automatically when the careers page loads.
"""

import asyncio
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

CAREERS_URL = "https://www.ibm.com/careers/search?location=India"


class IBMScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url or CAREERS_URL, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("[IBM] Playwright not installed for %s", self.company)
            return

        all_hits = []
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

                async def handle_response(response):
                    if "search/api/v2" in response.url:
                        try:
                            data = await response.json()
                            hits = data.get("hits", {}).get("hits", [])
                            all_hits.extend(hits)
                        except Exception:
                            pass

                page.on("response", handle_response)

                await page.goto(self.url, timeout=self.config.timeout_seconds * 1000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass

                # Scroll to load more
                for _ in range(10):
                    try:
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await asyncio.sleep(1.5)
                    except Exception:
                        break

        except Exception as e:
            logger.error("[IBM] Failed for %s: %s", self.company, e)
            return
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

        # Deduplicate and yield India jobs
        seen = set()
        for hit in all_hits:
            src = hit.get("_source", {})
            location = src.get("field_keyword_19", "")

            # Filter for India
            if not location or "IN" not in location.upper():
                continue

            job_url = src.get("url", "")
            if job_url in seen:
                continue
            seen.add(job_url)

            title = src.get("title", "")

            yield RawJob(
                company=self.company,
                title=title,
                location=location,
                url=job_url,
                description=src.get("description"),
                employment_type=src.get("field_keyword_17"),
                date_posted=None,
                source_ats="ibm",
            )

        logger.info("[IBM] %s: yielded %d unique India jobs", self.company, len(seen))
