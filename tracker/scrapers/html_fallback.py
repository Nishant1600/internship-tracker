"""
Generic HTML fallback scraper.

Uses Playwright to load a career page and extract job listings via a
configurable CSS selector from config.yaml.

This is inherently fragile — it depends on the page's DOM structure which
can change at any time. Documented as best-effort only.

NOTE: Playwright browser download required:
    playwright install chromium

If Playwright is not available, this scraper logs a warning and returns empty.
"""

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


class HTMLFallbackScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)
        self._css_selector = company.css_selector or "div.job-listing"

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            self._log_warning("Playwright not installed. Install with: playwright install chromium")
            return

        browser = None
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=self.config.headless,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                )
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                await page.goto(self.url, timeout=self.config.timeout_seconds * 1000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass

                for _ in range(3):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(1000)

                try:
                    await page.wait_for_selector(self._css_selector, timeout=10000)
                except Exception:
                    pass

                seen = set()
                max_pages = 10
                total_jobs = 0

                for page_num in range(1, max_pages + 1):
                    cards = await page.query_selector_all(self._css_selector)
                    if not cards:
                        if page_num == 1:
                            self._log_warning(
                                f"No elements matched CSS selector '{self._css_selector}' on {self.url}"
                            )
                        break

                    for card in cards:
                        parsed = await self._parse_card(card)
                        if parsed:
                            key = (parsed.title, parsed.location or "")
                            if key not in seen:
                                seen.add(key)
                                total_jobs += 1
                                yield parsed

                    next_btn = await page.query_selector('button:has-text("Go to next page"), button:has-text("Next")')
                    if not next_btn:
                        break

                    is_disabled = await next_btn.get_attribute("disabled")
                    if is_disabled is not None:
                        break

                    try:
                        await next_btn.click()
                        await page.wait_for_timeout(2000)
                        await page.wait_for_load_state("networkidle")
                    except Exception:
                        break

                self._log_info(f"Total jobs scraped: {total_jobs}")
        except Exception as e:
            self._log_error(f"Playwright error on {self.url}: {e}")
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def _parse_card(self, card) -> RawJob | None:
        title = await self._get_text(card, "h2, h3, h4, h5, h6, .title, .job-title, [data-job-title]")
        if not title:
            text = (await card.inner_text()).strip()
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            skip = {"HIRING", "APPLY", "View Details", "APPLY NOW", "View and Apply", "Nykaa", "Search jobs", "Showing"}
            for line in lines:
                if line not in skip and not line.startswith("Full-time") and not line.startswith("Part-time") and not line.startswith("Showing") and "nykaa.com" not in line and "preferred destination" not in line.lower():
                    title = line
                    break

        if not title:
            return None

        location = await self._get_text(card, ".location, .job-location, [data-location]")
        if location:
            location = location.replace("Location :", "").replace("Location:", "").strip()
        if not location:
            try:
                divs = await card.query_selector_all("div")
                for div in divs:
                    text = (await div.inner_text()).strip()
                    if any(city in text for city in ["Mumbai", "Bangalore", "Bengaluru", "Hyderabad", "Pune", "Delhi", "Noida", "Gurgaon", "Chennai", "Kolkata", "India", "Remote"]):
                        for part in text.split("  "):
                            part = part.strip()
                            if part and any(city in part for city in ["Mumbai", "Bangalore", "Bengaluru", "Hyderabad", "Pune", "Delhi", "Noida", "Gurgaon", "Chennai", "Kolkata", "India", "Remote"]):
                                location = part.split("In Office")[0].split("Remote")[0].split("Hybrid")[0].split("(Work From Office)[0").split("Work From Office")[0].strip()
                                break
                        if location:
                            break
            except Exception:
                pass
        if not location:
            text = (await card.inner_text()).strip()
            for line in text.split("\n"):
                line = line.strip()
                if "Job Location" in line:
                    idx = text.index("Job Location")
                    after = text[idx + len("Job Location"):].strip()
                    loc_line = after.split("\n")[0].strip()
                    if loc_line and not loc_line.startswith("("):
                        location = loc_line
                    break
        if not location:
            tds = await card.query_selector_all("td")
            if len(tds) >= 2:
                loc_text = (await tds[1].inner_text()).strip()
                if loc_text and ("-" in loc_text or any(c in loc_text for c in ["IN-", "US-", "UK-", "India", "Bangalore", "Hyderabad", "Pune"])):
                    location = loc_text
        if not location:
            text = (await card.inner_text()).strip()
            for line in text.split("\n"):
                line = line.strip()
                if "·" in line and any(c in line for c in ["Bangalore", "Hyderabad", "Pune", "Mumbai", "Delhi", "Noida", "Gurgaon", "Lucknow", "Chennai", "Kolkata", "India"]):
                    location = line
                    break
        if not location:
            try:
                lines = [l.strip() for l in (await card.inner_text()).strip().split("\n") if l.strip()]
                skip_texts = {"Apply now", "Apply", "View Details", "APPLY NOW", "Click to view→", "Click to view", "Intern", "Full-Time", "Part-Time", "Contract", "Temporary", "APPLY", "SHARE", "- Onsite", "- Remote", "- Hybrid", "Onsite", "Remote", "Hybrid"}
                # Try to find location - check all lines, not just after line 2
                for line in lines[1:]:
                    if line not in skip_texts and not line.startswith("Full-time") and not line.startswith("Part-time") and not line.startswith("Job ID:") and not line.startswith("1\xa0") and not re.match(r'\d+\s*-\s*\d+\s*Years', line) and not re.match(r'^[\u2022\-\*]\s', line):
                        location = line
                        break
            except Exception:
                pass

        url = await self._get_attr(card, "a", "href")
        if not url:
            url = await card.get_attribute("href")
        if not url:
            try:
                parent_a = await card.evaluate('el => el.closest("a") ? el.closest("a").href : null')
                if parent_a:
                    url = parent_a
            except Exception:
                pass
        description = await self._get_text(card, ".description, .job-description, .summary")
        employment_type = await self._get_text(card, ".type, .job-type, .employment-type")
        date_posted = await self._get_text(card, ".date, .posted-date, .job-date")

        if url and not url.startswith("http"):
            from urllib.parse import urljoin
            url = urljoin(self.url, url)

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=url or "",
            description=description,
            employment_type=employment_type,
            date_posted=date_posted,
            source_ats="html",
        )

    async def _get_text(self, card, selector: str) -> str | None:
        try:
            el = await card.query_selector(selector)
            if el:
                text = await el.inner_text()
                return text.strip() or None
        except Exception:
            pass
        return None

    async def _get_attr(self, card, selector: str, attr: str) -> str | None:
        try:
            el = await card.query_selector(selector)
            if el:
                val = await el.get_attribute(attr)
                return val.strip() if val else None
        except Exception:
            pass
        return None

    def _log_warning(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").warning("[HTMLFallback] %s", msg)

    def _log_error(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").error("[HTMLFallback] %s", msg)

    def _log_info(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").info("[HTMLFallback] %s", msg)
