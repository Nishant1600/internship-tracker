"""
Workday scraper.

Scrapes Workday career sites with automatic pagination.
Loads the career page, extracts job listings, and clicks "Next"
to fetch all available pages.

REQUIRES: playwright install chromium
"""

import asyncio
from typing import AsyncIterator

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

WORKDAY_JOB_CARD_SELECTORS = [
    "a[data-automation-id='jobTitle']",
    "li[data-automation-id='jobRow']",
    "div[data-automation-id='jobListing']",
    "div.job-listing",
    "tr[data-automation-id='jobRow']",
    "article[data-automation-id*='job']",
]

WORKDAY_NEXT_BUTTON_SELECTORS = [
    "button[data-automation-id='nextPage']",
    "button[aria-label='Next']",
    "button[aria-label='next']",
    "nav[aria-label='pagination'] button:last-child",
    "li[data-automation-id='nextPage'] button",
]

MAX_PAGES = 100
JOBS_PER_PAGE = 20
PAGE_RESTART_INTERVAL = 25


class WorkdayScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            self._log_warning("Playwright not installed (install: playwright install chromium)")
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
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass

                for btn_sel in [
                    "#onetrust-accept-btn-handler",
                    "button:has-text('Accept All Cookies')",
                    "button:has-text('Accept')",
                    "button:has-text('I Accept')",
                    "button:has-text('Allow All')",
                    "button:has-text('Accept Cookies')",
                ]:
                    try:
                        btn = await page.query_selector(btn_sel)
                        if btn and not await btn.is_hidden():
                            await btn.click()
                            await asyncio.sleep(2)
                            break
                    except Exception:
                        pass

                total_jobs = await self._get_total_jobs(page)
                if total_jobs is not None:
                    total_pages = (total_jobs + JOBS_PER_PAGE - 1) // JOBS_PER_PAGE
                    self._log_info(f"Detected {total_jobs} jobs ({total_pages} pages)")
                    if total_pages > MAX_PAGES:
                        self._log_warning(
                            f"Skipping {self.company}: {total_jobs} jobs "
                            f"exceeds {MAX_PAGES} page limit"
                        )
                        return
                else:
                    self._log_info("Could not detect total job count, scraping first page only")
                    max_pages = 1
                    total_pages = 1

                active_selector = None
                total_scraped = 0
                seen = set()

                for page_num in range(1, total_pages + 1):
                    cards = []
                    if active_selector:
                        cards = await page.query_selector_all(active_selector)
                    else:
                        for selector in WORKDAY_JOB_CARD_SELECTORS:
                            cards = await page.query_selector_all(selector)
                            if cards:
                                active_selector = selector
                                self._log_info(f"Using selector '{selector}' for job cards")
                                break

                    if not cards:
                        if page_num == 1:
                            body_text = await page.inner_text("body")
                            lines = [l.strip() for l in body_text.split("\n") if l.strip()]
                            self._log_warning(
                                f"No job cards found on {self.url}. "
                                f"Page loaded but no known selectors matched. "
                                f"Page has {len(lines)} lines of text."
                            )
                        break

                    self._log_info(f"Page {page_num}/{total_pages}: {len(cards)} job cards")
                    for card in cards:
                        parsed = await self._parse_card(card)
                        if parsed:
                            key = (parsed.title, parsed.location or "")
                            if key not in seen:
                                seen.add(key)
                                total_scraped += 1
                                yield parsed
                            else:
                                self._log_info(f"Skipping duplicate: {parsed.title} | {parsed.location}")

                    if page_num < total_pages:
                        if page_num % PAGE_RESTART_INTERVAL == 0:
                            try:
                                await page.close()
                            except Exception:
                                pass
                            page = await context.new_page()
                            await page.goto(self.url, timeout=self.config.timeout_seconds * 1000)
                            try:
                                await page.wait_for_load_state("networkidle", timeout=20000)
                            except Exception:
                                pass
                            self._log_info(f"Restarted page at page {page_num} to prevent memory buildup")
                            for _ in range(page_num - 1):
                                nxt = await self._find_next_button(page)
                                if not nxt:
                                    self._log_warning(f"Could not resume pagination at page {page_num}, stopping")
                                    break
                                try:
                                    await nxt.click()
                                    await asyncio.sleep(2)
                                    try:
                                        await page.wait_for_load_state("networkidle", timeout=15000)
                                    except Exception:
                                        pass
                                    await asyncio.sleep(1)
                                except Exception:
                                    break
                            else:
                                self._log_info(f"Resumed at page {page_num}")

                        next_btn = await self._find_next_button(page)
                        if not next_btn:
                            self._log_info(f"No next button found after page {page_num}. Done.")
                            break

                        try:
                            await next_btn.click()
                            await asyncio.sleep(3)
                            try:
                                await page.wait_for_load_state("networkidle", timeout=20000)
                            except Exception:
                                pass
                            await asyncio.sleep(2)
                        except Exception as e:
                            self._log_warning(f"Failed to click next on page {page_num}: {e}")
                            break

                self._log_info(f"Total jobs scraped: {total_scraped}")
        except Exception as e:
            self._log_error(f"Workday scraping failed for {self.url}: {e}")
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def _get_total_jobs(self, page) -> int | None:
        try:
            body_text = await page.inner_text("body")
            import re
            patterns = [
                r'of\s+(\d[\d,]*)\s+jobs',
                r'(\d[\d,]*)\s+jobs?\s+found',
                r'(\d[\d,]*)\s+results?',
                r'Showing\s+\d+[-–]\d+\s+of\s+(\d[\d,]*)',
                r'(\d[\d,]*)\s+total',
                r'Page\s+\d+\s+of\s+(\d[\d,]*)',
            ]
            for pattern in patterns:
                match = re.search(pattern, body_text, re.IGNORECASE)
                if match:
                    count_str = match.group(1).replace(',', '')
                    return int(count_str)
        except Exception:
            pass
        return None

    async def _find_next_button(self, page):
        for selector in WORKDAY_NEXT_BUTTON_SELECTORS:
            try:
                btn = await page.query_selector(selector)
                if btn:
                    is_disabled = await btn.get_attribute("disabled")
                    is_aria_disabled = await btn.get_attribute("aria-disabled")
                    is_hidden = await btn.is_hidden()
                    if is_disabled is None and is_aria_disabled != "true" and not is_hidden:
                        return btn
            except Exception:
                continue

        try:
            btn = await page.query_selector("button:has-text('Next')")
            if btn and not await btn.is_hidden():
                is_disabled = await btn.get_attribute("disabled")
                is_aria_disabled = await btn.get_attribute("aria-disabled")
                if is_disabled is None and is_aria_disabled != "true":
                    return btn
        except Exception:
            pass

        return None

    async def _parse_card(self, card) -> RawJob | None:
        title_el = await card.query_selector(
            "a[data-automation-id='jobTitle'], "
            "a.job-title, "
            "h3 a, h2 a, "
            "[data-automation-id*='title'] a"
        )
        title = None
        url = None
        if title_el:
            title = (await title_el.inner_text()).strip()
            url = await title_el.get_attribute("href")
        else:
            tag = await card.evaluate("el => el.tagName")
            if tag == "A":
                title = (await card.inner_text()).strip()
                url = await card.get_attribute("href")
        if not title:
            title_text = await card.inner_text()
            lines = [l.strip() for l in title_text.split("\n") if l.strip()]
            title = lines[0] if lines else None

        if not title:
            return None

        location = None
        parent = await card.evaluate_handle("el => el.closest('li') || el.closest('tr') || el.closest('div[class*=job]') || el.parentElement")
        if parent:
            loc_el = await parent.query_selector(
                "[data-automation-id='jobLocation'], "
                "[data-automation-id='locations'], "
                ".job-location, "
                "[data-automation-id*='location'], "
                "ul[data-automation-id='subtitle'] li:first-child"
            )
            if loc_el:
                location = (await loc_el.inner_text()).strip() or None
                if location:
                    lines = [l.strip() for l in location.split("\n") if l.strip()]
                    location = lines[1] if len(lines) > 1 else lines[0] if lines else None

            if not location:
                text = (await parent.inner_text()).strip()
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                for i, line in enumerate(lines):
                    if line.lower() in ("locations", "location") and i + 1 < len(lines):
                        location = lines[i + 1]
                        break

        if url and not url.startswith("http"):
            base = self.url.rstrip("/")
            url = base + "/" + url.lstrip("/")

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=url or "",
            description=None,
            employment_type=None,
            date_posted=None,
            source_ats="workday",
        )

    def _log_warning(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").warning("[Workday] %s", msg)

    def _log_error(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").error("[Workday] %s", msg)

    def _log_info(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").info("[Workday] %s", msg)
