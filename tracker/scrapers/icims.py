"""
iCIMS scraper.

BEST-EFFORT ONLY. iCIMS career pages are tenant-specific and do not
have a consistent public JSON API. This scraper uses the generic HTML
fallback approach with Playwright.

If Playwright is not available, or if the page structure is incompatible,
the scraper returns empty — it never crashes the pipeline.
"""

from tracker.config import CompanyConfig, ScraperConfig
from tracker.scrapers.html_fallback import HTMLFallbackScraper


class iCIMSScraper(HTMLFallbackScraper):
    """
    iCIMS-specific overrides for the HTML fallback scraper.
    Uses the same Playwright + CSS selector approach with iCIMS-specific defaults.
    """

    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        if not company.css_selector:
            company.css_selector = (
                "div.iCIMS_JobsTable > div.row, "
                "div.bs-row, "
                "[data-job-id], "
                "div.job-row"
            )
        super().__init__(company, config)
