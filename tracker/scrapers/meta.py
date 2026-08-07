"""
Meta Careers scraper.

Uses Playwright to scrape Meta's career site.
Extracts job listings from the job search page.

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


class MetaScraper(BaseScraper):
    """Scrape Meta Careers using Playwright."""

    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("[Meta] Playwright not installed (install: playwright install chromium)")
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

                # Extract job links using JavaScript
                jobs_data = await page.evaluate("""() => {
                    const jobs = [];
                    const links = document.querySelectorAll('a[href*="job_details"]');
                    for (const link of links) {
                        const href = link.getAttribute('href') || '';
                        const innerText = link.innerText.trim();
                        if (innerText && href) {
                            jobs.push({text: innerText, href: href});
                        }
                    }
                    return jobs;
                }""")

                seen = set()
                total_scraped = 0

                for job in jobs_data:
                    text = job.get("text", "")
                    href = job.get("href", "")

                    if not text or len(text) < 5:
                        continue

                    # Parse job info from innerText
                    # Format: "Title\nLocation\nTeam\nDepartment" (with newlines)
                    lines = [l.strip() for l in text.split("\n") if l.strip()]

                    if len(lines) < 2:
                        continue

                    title = lines[0]
                    location = lines[1] if len(lines) >= 2 else None

                    # Skip entries that look like duplicates or navigation
                    if title in seen or "cookie" in title.lower() or "privacy" in title.lower():
                        continue
                    seen.add(title)

                    # Build full URL
                    if href and not href.startswith("http"):
                        href = f"https://www.metacareers.com{href}"

                    total_scraped += 1
                    yield RawJob(
                        company=self.company,
                        title=title,
                        location=location,
                        url=href,
                        description=None,
                        employment_type=None,
                        date_posted=None,
                        source_ats="meta",
                    )

                logger.info("[Meta] Total jobs scraped: %d", total_scraped)

        except Exception as e:
            logger.error("[Meta] Scraping failed for %s: %s", self.url, e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
