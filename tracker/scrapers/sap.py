"""
SAP scraper.

Scrapes SAP's careers page at jobs.sap.com using Playwright.
Searches multiple India locations (Bangalore, Pune, Hyderabad, etc.).
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

INDIA_CITIES = ["Bangalore", "Pune"]
BASE_URL = "https://jobs.sap.com/search/?q=&location={city}&sortColumn=referencedate&sortDirection=desc"


class SAPScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url or "https://jobs.sap.com", config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("[SAP] Playwright not installed for %s", self.company)
            return

        seen_urls = set()
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

                for city in INDIA_CITIES:
                    page = await context.new_page()
                    url = BASE_URL.format(city=city)

                    try:
                        await page.goto(url, timeout=45000)
                        try:
                            await page.wait_for_load_state("networkidle", timeout=20000)
                        except Exception:
                            pass

                        links = await page.query_selector_all("a[href*='/job/']")
                        for link in links:
                            text = (await link.inner_text()).strip()
                            href = await link.get_attribute("href")

                            if not text or not href:
                                continue

                            if href in seen_urls:
                                continue
                            seen_urls.add(href)

                            lines = [l.strip() for l in text.split("\n") if l.strip()]
                            title = lines[0] if lines else text

                            full_url = href
                            if not full_url.startswith("http"):
                                full_url = f"https://jobs.sap.com{href}"

                            yield RawJob(
                                company=self.company,
                                title=title,
                                location=f"{city}, India",
                                url=full_url,
                                description=None,
                                employment_type=None,
                                date_posted=None,
                                source_ats="successfactors",
                            )

                    except Exception as e:
                        logger.warning("[SAP] Failed for city %s: %s", city, e)
                    finally:
                        try:
                            await page.close()
                        except Exception:
                            pass

        except Exception as e:
            logger.error("[SAP] Failed for %s: %s", self.company, e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

        logger.info("[SAP] %s: yielded %d unique India jobs", self.company, len(seen_urls))
