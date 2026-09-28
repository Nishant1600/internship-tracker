import json
from pathlib import Path

import pytest
import respx
from httpx import Response

from tracker.config import CompanyConfig, ScraperConfig
from tracker.scrapers.ashby import AshbyScraper

FIXTURES = Path(__file__).resolve().parent / "fixtures"

PUBLIC_GET = "https://api.ashbyhq.com/posting-api/job-board/perplexity"
LEGACY_POST = "https://api.ashbyhq.com/posting-public/getPostings"


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


def _fixture() -> dict:
    with open(FIXTURES / "ashby_fixture.json") as f:
        return json.load(f)


def _assert_jobs(jobs):
    assert len(jobs) == 2
    assert jobs[0].company == "Perplexity"
    assert jobs[0].title == "Software Engineer Intern"
    assert "Bangalore" in (jobs[0].location or "")
    assert jobs[0].employment_type == "Intern"
    assert jobs[0].source_ats == "ashby"
    assert jobs[0].url.startswith("https://")
    assert jobs[1].title == "Data Science Intern"


@pytest.mark.asyncio
async def test_ashby_fetches_public_job_board(ashby_config, scraper_config):
    """Primary path: unauthenticated GET posting-api/job-board/<board>."""
    scraper = AshbyScraper(ashby_config, scraper_config)

    # shape of the public GET feed: jobUrl/publishedAt instead of hostedUrl/publishedDate
    postings = [
        {**p, "jobUrl": p["hostedUrl"], "publishedAt": p["publishedDate"]}
        for p in _fixture()["postings"]
    ]
    async with respx.mock:
        respx.get(PUBLIC_GET).respond(json={"jobs": postings})
        jobs = [job async for job in scraper.fetch()]

    _assert_jobs(jobs)


@pytest.mark.asyncio
async def test_ashby_falls_back_to_legacy_post(ashby_config, scraper_config):
    """If the GET feed is gone, the legacy POST endpoint is still tried."""
    scraper = AshbyScraper(ashby_config, scraper_config)

    async with respx.mock:
        respx.get(PUBLIC_GET).respond(status_code=404)
        respx.post(LEGACY_POST).respond(json=_fixture())
        jobs = [job async for job in scraper.fetch()]

    _assert_jobs(jobs)


@pytest.mark.asyncio
async def test_ashby_handles_401(ashby_config, scraper_config):
    """Both endpoints unusable (POST needs an API key now) -> empty, no raise."""
    scraper = AshbyScraper(ashby_config, scraper_config)

    async with respx.mock:
        respx.get(PUBLIC_GET).respond(status_code=401)
        respx.post(LEGACY_POST).respond(status_code=401)
        jobs = [job async for job in scraper.fetch()]
    assert len(jobs) == 0
