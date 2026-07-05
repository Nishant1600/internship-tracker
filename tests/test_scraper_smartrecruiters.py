import json
from pathlib import Path

import pytest
import respx
from httpx import Response

from tracker.config import CompanyConfig, ScraperConfig
from tracker.scrapers.smartrecruiters import SmartRecruitersScraper

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def sr_config() -> CompanyConfig:
    return CompanyConfig(
        name="Coinbase",
        ats="smartrecruiters",
        url="https://api.smartrecruiters.com/v1/companies/coinbase/postings",
    )


@pytest.fixture
def scraper_config() -> ScraperConfig:
    return ScraperConfig(timeout_seconds=10, retry_count=1, retry_backoff_seconds=1)


@pytest.mark.asyncio
async def test_sr_parses_postings(sr_config, scraper_config):
    fixture_path = FIXTURES / "smartrecruiters_fixture.json"
    with open(fixture_path) as f:
        raw_data = json.load(f)

    scraper = SmartRecruitersScraper(sr_config, scraper_config)

    async with respx.mock:
        respx.get(
            "https://api.smartrecruiters.com/v1/companies/coinbase/postings"
        ).respond(json=raw_data)
        jobs = [job async for job in scraper.fetch()]

    assert len(jobs) == 2
    assert jobs[0].company == "Coinbase"
    assert jobs[0].title == "Software Engineer Intern"
    assert "Bangalore" in (jobs[0].location or "")
    assert jobs[0].source_ats == "smartrecruiters"


@pytest.mark.asyncio
async def test_sr_handles_404(sr_config, scraper_config):
    scraper = SmartRecruitersScraper(sr_config, scraper_config)

    async with respx.mock:
        respx.get(
            "https://api.smartrecruiters.com/v1/companies/coinbase/postings"
        ).respond(status_code=404)
        jobs = [job async for job in scraper.fetch()]
    assert len(jobs) == 0
