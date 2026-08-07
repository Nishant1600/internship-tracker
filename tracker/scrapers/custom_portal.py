"""
Custom portal scraper.

A generic Playwright-based scraper for career portals that don't fit
standard ATS patterns (Taleo, Darwinbox, custom-built, etc.).

Uses a broad set of CSS selectors and heuristic text parsing.

BEST-EFFORT ONLY — many custom portals require site-specific handling.
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

PORTAL_SELECTORS = [
    "a.group",
    "li.job",
    "div[class*='jobCard']:not([class*='Wrapper']):not([class*='Content']):not([class*='Location']):not([class*='Experience'])",
    "ul[class*='jobCard'] li",
    "div[class*='card-info']",
    "div.title2",
    "div[class*='job-card-header']",
    "article[class*='result']",
    "article",
    "div.job-listing",
    "div.job-card",
    "div.job-item",
    "li.job-item",
    "article.job-item",
    "div[data-job-id]",
    "div[data-jobid]",
    "tr.data-row",
    "div.search-result",
    "div.career-item",
    "li.opening",
    "div.opening",
    "a[href*='/job/']",
    "a[href*='job']",
]


class CustomPortalScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("[CustomPortal] Playwright not installed for %s", self.company)
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
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass

                for selector in PORTAL_SELECTORS:
                    cards = await page.query_selector_all(selector)
                    if cards and len(cards) > 1:
                        logger.info("[CustomPortal] %s: %d jobs with '%s'", self.company, len(cards), selector)
                        for card in cards:
                            job = await self._parse_card(card)
                            if job:
                                yield job
                        break
                else:
                    # Try single-card selectors
                    for selector in PORTAL_SELECTORS:
                        cards = await page.query_selector_all(selector)
                        if cards:
                            logger.info("[CustomPortal] %s: single job with '%s'", self.company, selector)
                            job = await self._parse_card(cards[0])
                            if job:
                                yield job
                            break
                    else:
                        logger.warning("[CustomPortal] No job cards found for %s on %s", self.company, self.url)

        except Exception as e:
            logger.error("[CustomPortal] Failed for %s: %s", self.company, e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def _parse_card(self, card) -> RawJob | None:
        title_el = await card.query_selector(
            "h2 a, h3 a, h4 a, "
            "a[data-automation-id='jobTitle'], "
            "a.job-title, .job-title a, "
            "[data-automation-id*='title'] a, "
            ".opening a, .job-card-title a, "
            "[class*='jobCardTitle'] a, [class*='jobCardTitle'], "
            "h3[class*='job-card-title'], "
            "[class*='jobCard'] a"
        )
        title = None
        url = None
        skip_titles = ("IT", "BPS", "Save", "APPLY/SHORTLIST", "Apply/Shortlist", "Jobs", "View Details", "VIEW ALL JOBS", "START NOW", "APPLY NOW", "APPLY SHARE", "View openings", "Join us")
        if title_el:
            title = (await title_el.inner_text()).strip()
            url = await title_el.get_attribute("href")
        else:
            tag = await card.evaluate("el => el.tagName")
            if tag == "A":
                text = (await card.inner_text()).strip()
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                skip_a = ("Apply", "APPLY", "SAVE", "Save", "View", "Share")
                for line in lines:
                    if line not in skip_a and not line.startswith("0 -") and not line.startswith("1 ") and "Years" not in line and "Opening" not in line:
                        title = line
                        break
                url = await card.get_attribute("href")
        if title and title in skip_titles:
            title = None
        if not title:
            text = (await card.inner_text()).strip()
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            skip = ("IT", "BPS", "Save", "APPLY/SHORTLIST", "Apply/Shortlist", "Jobs", "View Details", "VIEW ALL JOBS", "START NOW", "APPLY NOW")
            for line in lines:
                if line not in skip and not line.startswith("Skills:") and not line.startswith("Experience:") and not line.startswith("Location:"):
                    title = line
                    break

        if not title:
            return None

        if not url:
            link = await card.query_selector("a[href*='JobDetails'], a[href*='job'], a[href*='/jobs/']")
            if link:
                url = await link.get_attribute("href")

        location = None
        loc_el = await card.query_selector(
            "[data-automation-id='jobLocation'], "
            ".job-location, [data-automation-id*='location'], "
            "[class*='jobCardLocation'], [class*='job-location'], "
            "[class*='jobLocation'], [class*='Location']"
        )
        if loc_el:
            location = (await loc_el.inner_text()).strip() or None

        if not location:
            text = (await card.inner_text()).strip()
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            for line in lines:
                if line.startswith("Location:"):
                    location = line.replace("Location:", "").strip()
                    break
            if not location:
                known_cities = [
                    "Bangalore", "Bengaluru", "Hyderabad", "Pune", "Mumbai", "Delhi",
                    "Noida", "Gurgaon", "Gurugram", "Chennai", "Kolkata", "Ahmedabad",
                    "Jaipur", "Lucknow", "India", "Remote", "WFH", "Work from Home",
                    "Trivandrum", "Thiruvananthapuram", "Cochin", "Kochi", "Indore",
                    "Bhopal", "Visakhapatnam", "Vizag", "Coimbatore", "Mysore",
                ]
                for line in lines:
                    if line == title or line in ("Expand job details", "Save", "APPLY", "APPLY/SHORTLIST", "Apply/Shortlist", "APPLY SHARE", "Share on Facebook", "Share on Linkedin", "Post on X App", "Email your friends"):
                        continue
                    if line.startswith(("Experience:", "Required Skill:", "Full time", "Part time", "Job ID:", "0 -", "1 Opening", "2 Opening")):
                        continue
                    if any(city.lower() in line.lower() for city in known_cities):
                        location = line
                        break
                    if len(line) < 40 and not line[0].isdigit() and "Years" not in line and "Opening" not in line:
                        location = line
                        break

        if not location and url:
            slug = url.rstrip("/").split("/")[-1]
            parts = slug.split("-")
            if len(parts) >= 2:
                location_code = parts[-1].upper()
                city = parts[-2].replace("_", " ").title() if len(parts) >= 3 else ""
                if location_code and len(location_code) == 2:
                    location = f"{city}, {location_code}" if city else location_code

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
            source_ats="custom-portal",
        )
