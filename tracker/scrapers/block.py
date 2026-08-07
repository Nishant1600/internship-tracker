"""
Block (Square) Careers scraper.

Uses Playwright to scrape Block's career site.
Extracts job listings from the jobs page.

REQUIRES: playwright install chromium
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


class BlockScraper(BaseScraper):
    """Scrape Block Careers using Playwright."""

    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("[Block] Playwright not installed (install: playwright install chromium)")
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

                # Scroll to load all jobs
                prev_count = 0
                for _ in range(20):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(2)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass

                    current_count = await page.evaluate("document.querySelectorAll('a[href*=\"job\"], a[href*=\"posting\"]').length")
                    if current_count == prev_count:
                        break
                    prev_count = current_count

                # Extract job links
                jobs_data = await page.evaluate("""() => {
                    const jobs = [];
                    const links = document.querySelectorAll('a[href*="job"], a[href*="posting"]');
                    for (const link of links) {
                        const text = link.innerText.trim();
                        const href = link.getAttribute('href') || '';
                        if (text.length > 10 && text.length < 200 && !text.includes('Search') && !text.includes('cookie')) {
                            jobs.push({text: text, href: href});
                        }
                    }
                    return jobs;
                }""")

                seen = set()
                total_scraped = 0

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
                        href = f"https://block.xyz{href}"

                    total_scraped += 1
                    yield RawJob(
                        company=self.company,
                        title=title,
                        location=location,
                        url=href,
                        description=None,
                        employment_type=None,
                        date_posted=None,
                        source_ats="block",
                    )

                logger.info("[Block] Total jobs scraped: %d", total_scraped)

        except Exception as e:
            logger.error("[Block] Scraping failed for %s: %s", self.url, e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
