"""
Qualcomm scraper.

Qualcomm uses Eightfold AI for their careers site at careers.qualcomm.com.
Jobs are paginated with 20 per page, 50 pages total for India.
"""

import asyncio
import logging
from typing import AsyncIterator

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper

logger = logging.getLogger("tracker")

try:
    from playwright.async_api import async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class QualcommScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("[Qualcomm] Playwright not installed")
            return

        search_url = "https://careers.qualcomm.com/careers?query=&location=India"

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

                await page.goto(search_url, timeout=30000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass

                await asyncio.sleep(5)

                seen = set()
                max_pages = 50

                for page_num in range(max_pages):
                    title_elements = await page.query_selector_all(
                        '[class*="title-"]'
                    )
                    if not title_elements:
                        break

                    for title_el in title_elements:
                        title = (await title_el.inner_text()).strip()
                        if not title or len(title) < 3:
                            continue

                        location = None
                        try:
                            parent = await title_el.evaluate_handle(
                                "el => el.parentElement?.parentElement"
                            )
                            if parent:
                                full_text = await parent.inner_text()
                                lines = [l.strip() for l in full_text.split("\n") if l.strip()]
                                if len(lines) > 1:
                                    location = lines[1]
                        except Exception:
                            pass

                        href = ""
                        try:
                            link_el = await title_el.evaluate_handle(
                                "el => el.closest('a') || el.parentElement?.closest('a')"
                            )
                            if link_el:
                                href = await link_el.get_attribute("href") or ""
                        except Exception:
                            pass

                        if not href.startswith("http"):
                            href = f"https://careers.qualcomm.com{href}"

                        key = f"{title}|{location}"
                        if key in seen:
                            continue
                        seen.add(key)

                        yield RawJob(
                            company=self.company,
                            title=title,
                            location=location,
                            url=href,
                            description=None,
                            employment_type=None,
                            date_posted=None,
                            source_ats="qualcomm",
                        )

                    next_btn = await page.query_selector(
                        'button[aria-label="Next jobs"]'
                    )
                    if not next_btn:
                        break

                    is_disabled = await next_btn.get_attribute("disabled")
                    if is_disabled is not None:
                        break

                    try:
                        await next_btn.click()
                        await asyncio.sleep(3)
                    except Exception:
                        break

                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass

        except Exception as e:
            logger.error("[Qualcomm] Scraping failed: %s", e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
