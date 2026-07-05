from typing import AsyncIterator

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper
from tracker.scrapers.greenhouse import GreenhouseScraper
from tracker.scrapers.lever import LeverScraper
from tracker.scrapers.ashby import AshbyScraper
from tracker.scrapers.smartrecruiters import SmartRecruitersScraper
from tracker.scrapers.bamboohr import BambooHRScraper
from tracker.scrapers.workday import WorkdayScraper
from tracker.scrapers.icims import iCIMSScraper
from tracker.scrapers.html_fallback import HTMLFallbackScraper


class UnsupportedScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)
        self._ats_type = company.ats

    async def fetch(self) -> AsyncIterator[RawJob]:
        import logging
        logging.getLogger("tracker").warning(
            "[%s] ATS type '%s' not yet implemented; skipping",
            self.company,
            self._ats_type,
        )
        if False:
            yield  # type: ignore


def get_scraper(company: CompanyConfig, config: ScraperConfig) -> BaseScraper:
    ats = company.ats.lower()
    scrapers = {
        "greenhouse": GreenhouseScraper,
        "lever": LeverScraper,
        "ashby": AshbyScraper,
        "smartrecruiters": SmartRecruitersScraper,
        "bamboohr": BambooHRScraper,
        "workday": WorkdayScraper,
        "icims": iCIMSScraper,
        "html": HTMLFallbackScraper,
    }
    cls = scrapers.get(ats)
    if cls is not None:
        return cls(company, config)
    return UnsupportedScraper(company, config)
