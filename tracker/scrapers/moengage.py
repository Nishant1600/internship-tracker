"""
MoEngage scraper.

MoEngage uses Trakstar (Hire.Trakstar.com) for their careers site.
Jobs are listed on the main page with title and location in HTML attributes.
"""

import html as html_mod
import logging
import re
from typing import AsyncIterator

import httpx

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper

logger = logging.getLogger("tracker")


class MoEngageScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        try:
            async with httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                },
            ) as client:
                resp = await client.get(self.url)
                resp.raise_for_status()
                html = resp.text

                titles = re.findall(
                    r'js-job-list-opening-name[^>]*title="([^"]+)"', html
                )
                locs = re.findall(
                    r'js-job-list-opening-loc[^>]*title="([^"]+)"', html
                )
                slugs = re.findall(r'href="(/jobs/[^"]+)"', html)

                seen = set()
                for i, (title, loc) in enumerate(zip(titles, locs)):
                    title = html_mod.unescape(title.strip())
                    loc = html_mod.unescape(loc.strip())
                    if title in seen:
                        continue
                    seen.add(title)

                    slug = slugs[i] if i < len(slugs) else ""
                    url = f"https://moengage.hire.trakstar.com{slug}" if slug else self.url

                    yield RawJob(
                        company=self.company,
                        title=title,
                        location=loc,
                        url=url,
                        description=None,
                        employment_type=None,
                        date_posted=None,
                        source_ats="moengage",
                    )

        except Exception as e:
            logger.error("[MoEngage] Scraping failed: %s", e)
