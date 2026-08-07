"""
PayU careers page scraper.

Scrapes https://careers.payu.in/PayU/go/_/514880/ which has a server-rendered
table layout. Uses httpx (no Playwright needed).
"""

import logging
from typing import AsyncIterator

import httpx
from bs4 import BeautifulSoup

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper

logger = logging.getLogger("tracker")

BASE_URL = "https://careers.payu.in"


class PayUScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            follow_redirects=True,
        ) as client:
            page = 1
            while True:
                url = self.url if page == 1 else f"{self.url}?q=&sortColumn=referencedate&sortDirection=desc&startRow={25 * (page - 1)}"
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        logger.warning("[PayU] HTTP %d for %s", resp.status_code, self.company)
                        return

                    soup = BeautifulSoup(resp.text, "html.parser")
                    rows = soup.select("tbody tr")
                    if not rows:
                        return

                    count = 0
                    for row in rows:
                        cells = row.find_all("td")
                        if len(cells) < 3:
                            continue

                        # Use desktop title (hidden-phone), skip mobile duplicate
                        title_el = cells[1].select_one("a.jobTitle-link")
                        if not title_el:
                            continue
                        title = title_el.get_text(strip=True)
                        if not title:
                            continue

                        location = cells[2].get_text(strip=True)

                        href = title_el.get("href", "")
                        url_full = f"{BASE_URL}{href}" if href.startswith("/") else href

                        yield RawJob(
                            company=self.company,
                            title=title,
                            location=location or None,
                            url=url_full or None,
                            description=None,
                            employment_type=None,
                            date_posted=None,
                            source_ats="html",
                        )
                        count += 1

                    logger.info("[PayU] Page %d: %d jobs for %s", page, count, self.company)

                    if count == 0:
                        return

                    # Check for next page
                    next_link = soup.select_one("li.next a") or soup.select_one('a[href*="startRow"]')
                    if not next_link:
                        return

                    page += 1

                except Exception as e:
                    logger.error("[PayU] Failed for %s: %s", self.company, e)
                    return
