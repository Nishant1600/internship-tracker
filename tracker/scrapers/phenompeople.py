"""
Phenom People scraper.

Phenom People is an AI-powered talent experience platform used by
Cognizant, Genpact, and others. Their career pages expose a REST API
that returns JSON job listings.

BEST-EFFORT ONLY — API structure may vary between tenants.
Falls back to Playwright when HTTP requests are blocked (403).
"""

import logging
from typing import AsyncIterator, Any

import httpx

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper

logger = logging.getLogger("tracker")

try:
    from playwright.async_api import async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    return str(val)


class PhenomPeopleScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        try:
            async with httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
                follow_redirects=True,
                headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
            ) as client:
                resp = await client.get(self.url)
                if resp.status_code == 404:
                    logger.warning("[PhenomPeople] 404 for %s", self.company)
                    return
                if resp.status_code == 403:
                    logger.warning("[PhenomPeople] 403 for %s, trying Playwright", self.company)
                    async for job in self._fetch_playwright():
                        yield job
                    return
                resp.raise_for_status()

                data = resp.json()
                jobs = self._extract_jobs(data)
                if not jobs:
                    logger.warning("[PhenomPeople] No jobs found in response for %s", self.company)
                    return

                for item in jobs:
                    parsed = self._parse_job(item)
                    if parsed:
                        yield parsed
        except Exception as e:
            logger.error("[PhenomPeople] Failed for %s: %s", self.company, e)

    async def _fetch_playwright(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("[PhenomPeople] Playwright not installed")
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
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass

                selectors = [
                    "div[class*='card']:has(a[href*='/jobs/'])",
                    "div[class*='card']:has(a[href*='/job/'])",
                    "li:has(a[href*='/job/'])",
                    "[data-ph-at-id='jobs-list-item']",
                    ".jobs-list-item",
                    "li.job-item",
                    "div.job-card",
                    "a[href*='/job/']",
                ]
                for selector in selectors:
                    cards = await page.query_selector_all(selector)
                    if cards:
                        logger.info("[PhenomPeople] %s: %d jobs with '%s'", self.company, len(cards), selector)
                        for card in cards:
                            job = await self._parse_card_playwright(card)
                            if job:
                                yield job
                        break
                else:
                    logger.warning("[PhenomPeople] No job cards found on %s", self.url)

        except Exception as e:
            logger.error("[PhenomPeople] Playwright scraping failed for %s: %s", self.url, e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def _parse_card_playwright(self, card) -> RawJob | None:
        title_el = await card.query_selector(
            "a[href*='/jobs/'], a[href*='/job/'], "
            "[data-ph-at-id='jobs-list-item-title'], "
            ".job-title, h2 a, h3 a"
        )
        title = None
        url = None
        if title_el:
            title = (await title_el.inner_text()).strip()
            url = await title_el.get_attribute("href")
        if not title:
            text = (await card.inner_text()).strip()
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            title = lines[0] if lines else None

        if not title or title == "Save":
            return None

        location = None
        loc_el = await card.query_selector(
            "[data-ph-at-id='jobs-list-item-location'], "
            "[class*='location'], .job-location"
        )
        if loc_el:
            location = (await loc_el.inner_text()).strip() or None

        if not location:
            text = (await card.inner_text()).strip()
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            for line in lines[1:]:
                if line != "Save" and not line.isdigit():
                    location = line
                    break

        if url and not url.startswith("http"):
            url = self.url.rstrip("/") + "/" + url.lstrip("/")

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=url or "",
            description=None,
            employment_type=None,
            date_posted=None,
            source_ats="phenompeople",
        )

    def _extract_jobs(self, data: Any) -> list[dict]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("jobs", "data", "results", "items", "requisitions", "jobRequisitions"):
                if key in data and isinstance(data[key], list):
                    return data[key]
                if key in data and isinstance(data[key], dict):
                    return self._extract_jobs(data[key])
        return []

    def _parse_job(self, item: dict) -> RawJob | None:
        title = _safe_str(
            item.get("title") or item.get("jobTitle") or item.get("name") or ""
        ).strip()
        if not title:
            return None

        location = _safe_str(
            item.get("location") or item.get("jobLocation") or ""
        ).strip() or None

        description = _safe_str(
            item.get("description") or item.get("jobDescription") or ""
        ).strip() or None

        url = _safe_str(item.get("url") or item.get("jobUrl") or item.get("applyUrl") or "").strip()
        if not url:
            job_id = item.get("jobId") or item.get("id") or item.get("requisitionId")
            if job_id:
                url = f"{self.url.rstrip('/')}/jobs/{job_id}"

        date_posted = _safe_str(
            item.get("datePosted") or item.get("postedDate") or item.get("createdAt") or ""
        ).strip() or None

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=url,
            description=description,
            employment_type=None,
            date_posted=date_posted,
            source_ats="phenompeople",
        )
