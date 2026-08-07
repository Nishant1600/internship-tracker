"""
Microsoft Careers scraper.

Uses Playwright to scrape Microsoft's career site.
Extracts job listings from the job search page with pagination.

REQUIRES: playwright install chromium
"""

import asyncio
import logging
import re
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

MAX_PAGES = 100


class MicrosoftScraper(BaseScraper):
    """Scrape Microsoft Careers using Playwright."""

    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("[Microsoft] Playwright not installed (install: playwright install chromium)")
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
                await asyncio.sleep(5)

                seen = set()
                total_scraped = 0

                for page_num in range(1, MAX_PAGES + 1):
                    # Extract jobs from current page
                    jobs_data = await page.evaluate("""() => {
                        const jobs = [];
                        const cards = document.querySelectorAll('[class*="job"], [class*="card"], article, li');
                        for (const card of cards) {
                            const link = card.querySelector('a[href*="job"], a[href*="position"]');
                            if (link) {
                                const text = card.innerText.trim();
                                const href = link.getAttribute('href') || '';
                                if (text.length > 10 && text.length < 300) {
                                    jobs.push({text: text, href: href});
                                }
                            }
                        }
                        return jobs;
                    }""")

                    new_count = 0
                    for job in jobs_data:
                        text = job.get("text", "")
                        href = job.get("href", "")

                        lines = [l.strip() for l in text.split("\n") if l.strip()]
                        if len(lines) < 1:
                            continue

                        title = lines[0]
                        location = lines[1] if len(lines) > 1 else None

                        if title in seen:
                            continue
                        seen.add(title)

                        if href and not href.startswith("http"):
                            href = f"https://jobs.careers.microsoft.com{href}"

                        total_scraped += 1
                        new_count += 1
                        yield RawJob(
                            company=self.company,
                            title=title,
                            location=location,
                            url=href,
                            description=None,
                            employment_type=None,
                            date_posted=None,
                            source_ats="microsoft",
                        )

                    logger.info("[Microsoft] Page %d: %d new jobs (total: %d)", page_num, new_count, total_scraped)

                    if new_count == 0:
                        break

                    # Click next page
                    next_btn = None
                    for sel in ["button[aria-label='Next']", "a[aria-label='Next']", "button:has-text('Next')"]:
                        try:
                            btn = await page.query_selector(sel)
                            if btn and not await btn.is_hidden():
                                is_disabled = await btn.get_attribute("disabled")
                                if is_disabled is None:
                                    next_btn = btn
                                    break
                        except Exception:
                            continue

                    if not next_btn:
                        break

                    try:
                        await next_btn.click()
                        await asyncio.sleep(3)
                        try:
                            await page.wait_for_load_state("networkidle", timeout=15000)
                        except Exception:
                            pass
                        await asyncio.sleep(2)
                    except Exception as e:
                        logger.warning("[Microsoft] Failed to click next: %s", e)
                        break

                logger.info("[Microsoft] Total jobs scraped: %d", total_scraped)

        except Exception as e:
            logger.error("[Microsoft] Scraping failed for %s: %s", self.url, e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
