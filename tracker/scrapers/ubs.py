"""
UBS TalentLink (Brassring) scraper.

Uses Playwright to load the Angular-based TalentLink portal, fills
the keyword search with 'India', clicks search, then extracts all
job data from the Angular scope.
"""

import html
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


class UBSScraper(BaseScraper):
    """Scraper for UBS (TalentLink/Brassring ATS)."""

    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)
        self._company_url = company.url

    async def fetch(self) -> AsyncIterator[RawJob]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("Playwright not installed — skipping %s", self.company)
            return

        browser = None
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=self.config.headless,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                    ],
                )
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1920, "height": 1080},
                )
                page = await context.new_page()

                try:
                    await page.goto(self.url, timeout=40_000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=20_000)
                    except Exception:
                        pass

                    # Accept cookie consent
                    try:
                        agree = page.locator("text=Agree to all")
                        if await agree.count() > 0:
                            await agree.first.click(timeout=5_000)
                            await page.wait_for_timeout(2000)
                    except Exception:
                        pass

                    # Fill keyword search with India and click search
                    try:
                        await page.fill(
                            'input[name="keyWordSearch"]',
                            "India",
                            timeout=5_000,
                        )
                        await page.wait_for_timeout(1000)

                        await page.click(
                            'button[ng-click="searchMatchedJobs(this)"]',
                            timeout=5_000,
                        )
                        await page.wait_for_timeout(8000)
                    except Exception as exc:
                        logger.warning("UBS search failed: %s", exc)
                        return

                    # Extract jobs from Angular scope
                    jobs_data = await page.evaluate(
                        """() => {
                        try {
                            const scope = angular.element(
                                document.querySelector('[ng-controller=searchResults]')
                            ).scope();
                            const jobs = scope.jobs || [];
                            return JSON.stringify(jobs.map(j => {
                                const title = j.Questions.find(
                                    q => q.QuestionName === 'jobtitle'
                                );
                                const loc = j.Questions.find(
                                    q => q.QuestionName === 'formtext23'
                                );
                                const dept = j.Questions.find(
                                    q => q.QuestionName === 'formtext21'
                                );
                                const reqid = j.Questions.find(
                                    q => q.QuestionName === 'reqid'
                                );
                                return {
                                    title: title ? title.Value : '',
                                    location: loc ? loc.Value : '',
                                    dept: dept ? dept.Value : '',
                                    reqid: reqid ? reqid.Value : '',
                                    link: j.Link
                                };
                            }));
                        } catch(e) {
                            return '[]';
                        }
                    }"""
                    )

                    import json

                    try:
                        jobs_list = json.loads(jobs_data)
                    except Exception:
                        logger.warning("Failed to parse UBS job data")
                        return

                    seen = set()
                    for job in jobs_list:
                        title = html.unescape(job.get("title", "")).strip()
                        location = html.unescape(job.get("location", "")).strip()
                        link = job.get("link", "")
                        reqid = job.get("reqid", "")

                        if not title:
                            continue

                        uid = f"{self.company}|{reqid or title}"
                        if uid in seen:
                            continue
                        seen.add(uid)

                        # Filter for India
                        loc_lower = location.lower()
                        if not any(
                            x in loc_lower
                            for x in [
                                "india",
                                "bengaluru",
                                "bangalore",
                                "pune",
                                "mumbai",
                                "noida",
                                "hyderabad",
                                "chennai",
                                "gurgaon",
                                "delhi",
                            ]
                        ):
                            continue

                        yield RawJob(
                            company=self.company,
                            title=title,
                            location=location,
                            url=link,
                            description=None,
                            employment_type=None,
                            date_posted=None,
                            source_ats="talentlink",
                        )

                except Exception as e:
                    logger.error("[UBS] Scraping failed for %s: %s", self.url, e)
        except Exception as e:
            logger.error("[UBS] Failed for %s: %s", self.company, e)
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
