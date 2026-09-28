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
from tracker.scrapers.tcs import TCSScraper
from tracker.scrapers.successfactors import SuccessFactorsScraper
from tracker.scrapers.phenompeople import PhenomPeopleScraper
from tracker.scrapers.custom_portal import CustomPortalScraper
from tracker.scrapers.custom_api import CustomAPIScraper
from tracker.scrapers.google import GoogleScraper
from tracker.scrapers.openai import OpenAIScraper
from tracker.scrapers.notion import NotionScraper
from tracker.scrapers.netflix import NetflixScraper
from tracker.scrapers.meta import MetaScraper
from tracker.scrapers.microsoft import MicrosoftScraper
from tracker.scrapers.block import BlockScraper
from tracker.scrapers.jobvite import JobviteScraper
from tracker.scrapers.qburst import QBurstScraper
from tracker.scrapers.swiggy import SwiggyScraper
from tracker.scrapers.zwayam import ZwayamScraper
from tracker.scrapers.linkedin import LinkedInScraper
from tracker.scrapers.kula import KulaScraper
from tracker.scrapers.turbohire import TurbohireScraper
from tracker.scrapers.payu import PayUScraper
from tracker.scrapers.walmart import WalmartScraper
from tracker.scrapers.atlassian import AtlassianScraper
from tracker.scrapers.paypal import EightfoldScraper
from tracker.scrapers.sap import SAPScraper
from tracker.scrapers.oracle import OracleScraper
from tracker.scrapers.ibm import IBMScraper
from tracker.scrapers.cisco import CiscoScraper
from tracker.scrapers.texas_instruments import TexasInstrumentsScraper
from tracker.scrapers.qualcomm import QualcommScraper
from tracker.scrapers.dell import DellScraper
from tracker.scrapers.netapp import NetAppScraper
from tracker.scrapers.nutanix import NutanixScraper
from tracker.scrapers.honeywell import HoneywellScraper
from tracker.scrapers.moengage import MoEngageScraper
from tracker.scrapers.morgan_stanley import MorganStanleyScraper
from tracker.scrapers.goldman_sachs import GoldmanSachsScraper
from tracker.scrapers.americanexpress import AmericanExpressScraper
from tracker.scrapers.hsbc import HSBCScraper
from tracker.scrapers.jpmorgan import JPMorganScraper
from tracker.scrapers.bnymellon import BNYMellonScraper
from tracker.scrapers.ubs import UBSScraper
from tracker.scrapers.amd import AMDScraper
from tracker.scrapers.arista import AristaScraper
from tracker.scrapers.hpe import HPEScraper


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


SCRAPERS: dict[str, type[BaseScraper]] = {
    "greenhouse": GreenhouseScraper,
    "lever": LeverScraper,
    "ashby": AshbyScraper,
    "smartrecruiters": SmartRecruitersScraper,
    "bamboohr": BambooHRScraper,
    "workday": WorkdayScraper,
    "icims": iCIMSScraper,
    "html": HTMLFallbackScraper,
    "tcs": TCSScraper,
    "successfactors": SuccessFactorsScraper,
    "phenompeople": PhenomPeopleScraper,
    "custom-portal": CustomPortalScraper,
    "custom-api": CustomAPIScraper,
    "google": GoogleScraper,
    "openai": OpenAIScraper,
    "notion": NotionScraper,
    "netflix": NetflixScraper,
    "meta": MetaScraper,
    "microsoft": MicrosoftScraper,
    "block": BlockScraper,
    "jobvite": JobviteScraper,
    "qburst": QBurstScraper,
    "swiggy": SwiggyScraper,
    "zwayam": ZwayamScraper,
    "linkedin": LinkedInScraper,
    "kula": KulaScraper,
    "turbohire": TurbohireScraper,
    "payu": PayUScraper,
    "walmart": WalmartScraper,
    "atlassian": AtlassianScraper,
    "eightfold": EightfoldScraper,
    "sap": SAPScraper,
    "oracle": OracleScraper,
    "ibm": IBMScraper,
    "cisco": CiscoScraper,
    "texasinstruments": TexasInstrumentsScraper,
    "qualcomm": QualcommScraper,
    "dell": DellScraper,
    "netapp": NetAppScraper,
    "nutanix": NutanixScraper,
    "honeywell": HoneywellScraper,
    "moengage": MoEngageScraper,
    "morganstanley": MorganStanleyScraper,
    "goldmansachs": GoldmanSachsScraper,
    "americanexpress": AmericanExpressScraper,
    "hsbc": HSBCScraper,
    "jpmorgan": JPMorganScraper,
    "bnymellon": BNYMellonScraper,
    "talentlink": UBSScraper,
    "amd": AMDScraper,
"arista": AristaScraper,
"hpe": HPEScraper,
}


def get_scraper(company: CompanyConfig, config: ScraperConfig) -> BaseScraper:
    cls = SCRAPERS.get(company.ats.lower())
    if cls is not None:
        return cls(company, config)
    return UnsupportedScraper(company, config)
