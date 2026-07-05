import json
from pathlib import Path

import pytest
import respx
from httpx import Response

from tracker.config import CompanyConfig, ScraperConfig
from tracker.scrapers.lever import LeverScraper

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def lever_config() -> CompanyConfig:
    return CompanyConfig(
        name="Razorpay",
        ats="lever",
        url="https://api.lever.co/v0/postings/razorpay?mode=json",
    )


@pytest.fixture
def scraper_config() -> ScraperConfig:
    return ScraperConfig(timeout_seconds=10, retry_count=1, retry_backoff_seconds=1)


@pytest.mark.asyncio
async def test_lever_parses_postings(lever_config, scraper_config):
    fixture_path = FIXTURES / "lever_fixture.json"
    with open(fixture_path) as f:
        raw_data = json.load(f)

    scraper = LeverScraper(lever_config, scraper_config)

    async with respx.mock:
        respx.get(
            "https://api.lever.co/v0/postings/razorpay"
        ).respond(json=raw_data)

        jobs = [job async for job in scraper.fetch()]

    assert len(jobs) == 3
    for job in jobs:
        assert job.company == "Razorpay"
        assert job.title
        assert job.source_ats == "lever"

    titles = [j.title for j in jobs]
    assert "Software Engineer Intern" in titles
    assert "Data Science Intern" in titles
    assert "Senior Software Engineer" in titles

    intern_jobs = [j for j in jobs if "Intern" in j.title]
    assert len(intern_jobs) == 2
    for ij in intern_jobs:
        assert ij.employment_type == "Intern"
        assert ij.location


@pytest.mark.asyncio
async def test_lever_handles_404(lever_config, scraper_config):
    scraper = LeverScraper(lever_config, scraper_config)

    async with respx.mock:
        respx.get(
            "https://api.lever.co/v0/postings/razorpay"
        ).respond(status_code=404)

        jobs = [job async for job in scraper.fetch()]
    assert len(jobs) == 0
