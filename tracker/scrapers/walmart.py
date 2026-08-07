"""
Walmart Labs scraper.

Intercepts the Walmart Labs India careers API (elsearch.json)
via Playwright. The API is called automatically when the page loads,
and we click "Load More" repeatedly to get all jobs.
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

INDIA_CAREERS_URL = "https://indiacareers.walmartlabs.com/content/globaltechindia/en_in/results.html"


class WalmartScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url or INDIA_CAREERS_URL, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("[Walmart] Playwright not installed for %s", self.company)
            return

        jobs = []
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
                    if "elsearch.json" in response.url:
                        try:
                            data = await response.json()
                            results = data.get("results", [])
                            for r in results:
                                if r.get("country") == "IN":
                                    jobs.append(r)
                        except Exception:
                            pass

                page.on("response", handle_response)

                await page.goto(self.url, timeout=self.config.timeout_seconds * 1000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass

                # Click "Load More" repeatedly to get all jobs
                for _ in range(15):
                    try:
                        load_more = await page.query_selector("text=Load More")
                        if load_more:
                            await load_more.click()
                            import asyncio
                            await asyncio.sleep(2)
                        else:
                            break
                    except Exception:
                        break

        except Exception as e:
            logger.error("[Walmart] Failed for %s: %s", self.company, e)
            return
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

        # Deduplicate by job_code
        seen = set()
        for r in jobs:
            job_id = r.get("job_code", r.get("title", ""))
            if job_id in seen:
                continue
            seen.add(job_id)

            title = r.get("title", "")
            city = r.get("city", "")
            state = r.get("state", "")
            apply_link = r.get("apply_link", "")

            location = city
            if state:
                location = f"{city}, {state}"

            yield RawJob(
                company=self.company,
                title=title,
                location=location,
                url=apply_link,
                description=r.get("preferred_qualifications_en"),
                employment_type=None,
                date_posted=r.get("last_updated"),
                source_ats="walmart",
            )

        logger.info("[Walmart] %s: yielded %d unique India jobs", self.company, len(seen))
