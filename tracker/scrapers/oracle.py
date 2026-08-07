"""
Oracle scraper.

Intercepts the Oracle HCM REST API via Playwright.
The API is called automatically when the careers page loads.
Supports pagination via offset parameter.
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

CAREERS_URL = "https://careers.oracle.com/en/sites/jobsearch/jobs?mode=location"


class OracleScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url or CAREERS_URL, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("[Oracle] Playwright not installed for %s", self.company)
            return

        all_requisitions = []
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
                    if "recruitingCEJobR" in response.url:
                        try:
                            data = await response.json()
                            items = data.get("items", [])
                            if items:
                                req_list = items[0].get("requisitionList", [])
                                all_requisitions.extend(req_list)
                        except Exception:
                            pass

                page.on("response", handle_response)

                await page.goto(self.url, timeout=self.config.timeout_seconds * 1000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass

                # Scroll to load more jobs
                for _ in range(15):
                    try:
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        import asyncio
                        await asyncio.sleep(1.5)
                    except Exception:
                        break

        except Exception as e:
            logger.error("[Oracle] Failed for %s: %s", self.company, e)
            return
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

        # Deduplicate and yield India jobs
        seen = set()
        for req in all_requisitions:
            if req.get("PrimaryLocationCountry") != "IN":
                continue

            job_id = req.get("Id", "")
            if job_id in seen:
                continue
            seen.add(job_id)

            title = req.get("Title", "")
            location = req.get("PrimaryLocation", "")
            posted = req.get("PostedDate")
            job_id_str = req.get("Id", "")

            url = f"https://careers.oracle.com/jobs/#en/sites/jobsearch/requisitions/detail/{job_id_str}"

            yield RawJob(
                company=self.company,
                title=title,
                location=location,
                url=url,
                description=req.get("ShortDescriptionStr"),
                employment_type=req.get("WorkerType"),
                date_posted=posted,
                source_ats="oracle",
            )

        logger.info("[Oracle] %s: yielded %d unique India jobs", self.company, len(seen))
