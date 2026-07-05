import json
from pathlib import Path

import pytest
import respx
from httpx import Response

from tracker.config import CompanyConfig, ScraperConfig
from tracker.scrapers.ashby import AshbyScraper

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def ashby_config() -> CompanyConfig:
    return CompanyConfig(
        name="Perplexity",
        ats="ashby",
        url="https://jobs.ashbyhq.com/perplexity",
    )


@pytest.fixture
def scraper_config() -> ScraperConfig:
    return ScraperConfig(timeout_seconds=10, retry_count=1, retry_backoff_seconds=1)


@pytest.mark.asyncio
async def test_ashby_parses_postings(ashby_config, scraper_config):
    fixture_path = FIXTURES / "ashby_fixture.json"
    with open(fixture_path) as f:
        raw_data = json.load(f)

    scraper = AshbyScraper(ashby_config, scraper_config)

    async with respx.mock:
        respx.post("https://api.ashbyhq.com/posting-public/getPostings").respond(
            json=raw_data
        )
        jobs = [job async for job in scraper.fetch()]

    assert len(jobs) == 2
    assert jobs[0].company == "Perplexity"
    assert jobs[0].title == "Software Engineer Intern"
    assert "Bangalore" in (jobs[0].location or "")
    assert jobs[0].employment_type == "Intern"
    assert jobs[0].source_ats == "ashby"
    assert jobs[1].title == "Data Science Intern"


@pytest.mark.asyncio
async def test_ashby_handles_401(ashby_config, scraper_config):
    scraper = AshbyScraper(ashby_config, scraper_config)

    async with respx.mock:
        respx.post("https://api.ashbyhq.com/posting-public/getPostings").respond(
            status_code=401
        )
        jobs = [job async for job in scraper.fetch()]
    assert len(jobs) == 0
