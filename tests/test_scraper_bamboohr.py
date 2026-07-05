import json
from pathlib import Path

import pytest
import respx
from httpx import Response

from tracker.config import CompanyConfig, ScraperConfig
from tracker.scrapers.bamboohr import BambooHRScraper

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def bamboo_config() -> CompanyConfig:
    return CompanyConfig(
        name="TestCompany",
        ats="bamboohr",
        url="https://testcompany.bamboohr.com/jobs/public/",
    )


@pytest.fixture
def scraper_config() -> ScraperConfig:
    return ScraperConfig(timeout_seconds=10, retry_count=1, retry_backoff_seconds=1)


@pytest.mark.asyncio
async def test_bamboohr_parses_jobs(bamboo_config, scraper_config):
    fixture_path = FIXTURES / "bamboohr_fixture.json"
    with open(fixture_path) as f:
        raw_data = json.load(f)

    scraper = BambooHRScraper(bamboo_config, scraper_config)

    async with respx.mock:
        respx.get(
            "https://testcompany.bamboohr.com/jobs/public/"
        ).respond(json=raw_data)
        jobs = [job async for job in scraper.fetch()]

    assert len(jobs) == 2
    assert jobs[0].company == "TestCompany"
    assert jobs[0].title == "Software Engineer Intern"
    assert "Bangalore" in (jobs[0].location or "")
    assert jobs[0].source_ats == "bamboohr"


@pytest.mark.asyncio
async def test_bamboohr_handles_404(bamboo_config, scraper_config):
    scraper = BambooHRScraper(bamboo_config, scraper_config)

    async with respx.mock:
        respx.get(
            "https://testcompany.bamboohr.com/jobs/public/"
        ).respond(status_code=404)
        jobs = [job async for job in scraper.fetch()]
    assert len(jobs) == 0
