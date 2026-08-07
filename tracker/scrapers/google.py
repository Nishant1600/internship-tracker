"""
Google Careers scraper.

Uses Playwright to scrape Google's career site (SPA built with Closure Library).
Extracts job data from embedded AF_initDataCallback and handles pagination
via scroll/click interactions.

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

GOOGLE_NEXT_BUTTON_SELECTORS = [
    "button[aria-label='Next']",
    "button[aria-label='next']",
    "a[aria-label='Next']",
    "button:has-text('Next')",
    "button:has-text('Load more')",
    "button:has-text('Show more')",
    "[data-page-number]",
    "button[jsname]:has-text('Next')",
]

MAX_PAGES = 100
PAGE_RESTART_INTERVAL = 25


class GoogleScraper(BaseScraper):
    """Scrape Google Careers using Playwright to handle SPA pagination."""

    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("[Google] Playwright not installed (install: playwright install chromium)")
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

                # Dismiss cookie banners if present
                for btn_sel in [
                    "#onetrust-accept-btn-handler",
                    "button:has-text('Accept All')",
                    "button:has-text('Accept')",
                    "button:has-text('I agree')",
                    "button:has-text('Got it')",
                ]:
                    try:
                        btn = await page.query_selector(btn_sel)
                        if btn and not await btn.is_hidden():
                            await btn.click()
                            await asyncio.sleep(1)
                            break
                    except Exception:
                        pass

                # Google uses ?page=N parameter for pagination (20 jobs per page)
                seen = set()
                total_scraped = 0
                max_pages = MAX_PAGES
                empty_pages = 0

                for page_num in range(1, max_pages + 1):
                    if page_num > 1 and (page_num - 1) % PAGE_RESTART_INTERVAL == 0:
                        try:
                            await page.close()
                        except Exception:
                            pass
                        page = await context.new_page()

                    url = f"{self.url}?page={page_num}"
                    await page.goto(url, timeout=self.config.timeout_seconds * 1000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        pass
                    await asyncio.sleep(2)

                    # Extract jobs from this page
                    page_jobs = await self._extract_embedded_jobs(page)
                    new_count = 0

                    for job in page_jobs:
                        key = (job.title, job.location or "")
                        if key not in seen:
                            seen.add(key)
                            total_scraped += 1
                            new_count += 1
                            yield job

                    logger.info("[Google] Page %d: %d new jobs (total: %d)", page_num, new_count, total_scraped)

                    # Stop if no new jobs found
                    if new_count == 0:
                        empty_pages += 1
                        if empty_pages >= 2:
                            break
                    else:
                        empty_pages = 0

                logger.info("[Google] Total jobs scraped: %d", total_scraped)

        except Exception as e:
            logger.error("[Google] Scraping failed for %s: %s", self.url, e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def _extract_embedded_jobs(self, page) -> list[RawJob]:
        """Extract jobs from AF_initDataCallback embedded in the page."""
        jobs = []
        try:
            content = await page.content()
            # Find ds:1 callback
            marker = "AF_initDataCallback({key: 'ds:1'"
            idx = content.find(marker)
            if idx < 0:
                return jobs

            data_start = content.find("data:", idx)
            if data_start < 0:
                return jobs

            # Find matching closing bracket
            depth = 0
            pos = data_start + 5
            started = False
            while pos < len(content):
                if content[pos] == "[":
                    depth += 1
                    started = True
                elif content[pos] == "]":
                    depth -= 1
                    if started and depth == 0:
                        break
                pos += 1

            data_str = content[data_start + 5:pos + 1]

            # Extract job entries: [job_id, title, url, ...]
            # Google format: ["jobId","title","url",[null,description,...],...]
            job_pattern = r'\["(\d{15,})","([^"]{3,150})","https://www\.google\.com'
            for job_id, title in re.findall(job_pattern, data_str):
                # Try to extract location from nearby data
                location = self._extract_location_from_data(data_str, job_id)

                url = f"https://www.google.com/about/careers/applications/jobs/results/{job_id}"

                jobs.append(RawJob(
                    company=self.company,
                    title=title,
                    location=location,
                    url=url,
                    description=None,
                    employment_type=None,
                    date_posted=None,
                    source_ats="google",
                ))
        except Exception as e:
            logger.debug("[Google] Failed to extract embedded jobs: %s", e)
        return jobs

    def _extract_location_from_data(self, data_str: str, job_id: str) -> str | None:
        """Try to extract location from the embedded data near a job ID."""
        try:
            # Find the job entry and look for location patterns
            # Google stores locations as: ["City, Country", ...]
            idx = data_str.find(f'"{job_id}"')
            if idx < 0:
                return None

            # Look for location-like strings after the job entry
            # Pattern: "City, State/Country" or just "City, Country"
            location_pattern = r'"([A-Z][a-z]+(?:\s[A-Z][a-z]+)*,\s*[A-Z]{2,})"'
            matches = re.findall(location_pattern, data_str[idx:idx + 2000])
            if matches:
                return matches[0]

            # Try broader pattern
            location_pattern = r'"([A-Z][a-z]+(?:\s[A-Z][a-z]+)*,\s*[A-Za-z]+)"'
            matches = re.findall(location_pattern, data_str[idx:idx + 2000])
            if matches:
                return matches[0]
        except Exception:
            pass
        return None

    async def _find_next_button(self, page):
        """Find the next page button using multiple selector strategies."""
        for selector in GOOGLE_NEXT_BUTTON_SELECTORS:
            try:
                btn = await page.query_selector(selector)
                if btn:
                    is_hidden = await btn.is_hidden()
                    is_disabled = await btn.get_attribute("disabled")
                    is_aria_disabled = await btn.get_attribute("aria-disabled")
                    if not is_hidden and is_disabled is None and is_aria_disabled != "true":
                        return btn
            except Exception:
                continue
        return None

    def _extract_jobs_from_api(self, data) -> list[RawJob]:
        """Extract jobs from intercepted API responses."""
        jobs = []
        try:
            if isinstance(data, dict):
                # Try common job data keys
                for key in ["jobs", "data", "results", "items", "postings"]:
                    if key in data and isinstance(data[key], list):
                        for item in data[key]:
                            job = self._parse_api_job(item)
                            if job:
                                jobs.append(job)
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        job = self._parse_api_job(item)
                        if job:
                            jobs.append(job)
        except Exception:
            pass
        return jobs

    def _parse_api_job(self, item: dict) -> RawJob | None:
        """Parse a single job from API response."""
        title = (
            item.get("title") or item.get("jobTitle") or
            item.get("name") or item.get("position") or ""
        ).strip()
        if not title:
            return None

        location = (
            item.get("location") or item.get("jobLocation") or
            item.get("primaryLocation") or ""
        ).strip() or None

        url = (
            item.get("url") or item.get("jobUrl") or
            item.get("absolute_url") or ""
        ).strip()

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=url or "",
            description=None,
            employment_type=None,
            date_posted=None,
            source_ats="google",
        )
