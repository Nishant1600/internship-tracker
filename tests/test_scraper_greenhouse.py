import json
from pathlib import Path

import pytest
import respx
from httpx import Response

from tracker.config import CompanyConfig, ScraperConfig
from tracker.scrapers.greenhouse import GreenhouseScraper

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def stripe_config() -> CompanyConfig:
    return CompanyConfig(
        name="Stripe",
        ats="greenhouse",
        url="https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true",
    )


@pytest.fixture
def scraper_config() -> ScraperConfig:
    return ScraperConfig(timeout_seconds=10, retry_count=1, retry_backoff_seconds=1)


@pytest.mark.asyncio
async def test_greenhouse_parses_jobs(stripe_config, scraper_config):
    fixture_path = FIXTURES / "greenhouse_stripe.json"
    with open(fixture_path) as f:
        raw_data = json.load(f)

    scraper = GreenhouseScraper(stripe_config, scraper_config)

    async with respx.mock:
        respx.get(
            "https://api.greenhouse.io/v1/boards/stripe/jobs"
        ).respond(json=raw_data)

        jobs = [job async for job in scraper.fetch()]

    assert len(jobs) == 3
    for job in jobs:
        assert job.company == "Stripe"
        assert job.title
        assert job.source_ats == "greenhouse"
        assert job.url
        assert "stripe" in job.company.lower()


@pytest.mark.asyncio
async def test_greenhouse_handles_404(stripe_config, scraper_config):
    scraper = GreenhouseScraper(stripe_config, scraper_config)

    async with respx.mock:
        respx.get(
            "https://api.greenhouse.io/v1/boards/stripe/jobs"
        ).respond(status_code=404)

        jobs = [job async for job in scraper.fetch()]
    assert len(jobs) == 0
