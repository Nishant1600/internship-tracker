import pytest
import respx
from datetime import datetime, timezone
from httpx import Response

from tracker.config import AggregatorSource
from tracker.scrapers.aggregator import AggregatorScraper


def sample_markdown():
    return """# 2026 SWE College Jobs

| Company | Role | Location | Application/Link | Date Posted |
|---------|------|----------|-----------------|-------------|
| Google | SWE Intern | Mountain View, CA | [Apply](https://google.com/jobs) | 2 days ago |
| Stripe | SWE Intern | Remote | [Apply](https://stripe.com/jobs) | 1 day ago |
| Jane Street | Quant Intern | New York | [Apply](https://janestreet.com/jobs) | Just posted |
| Meta | SWE Intern | Menlo Park | [Apply](https://meta.com/jobs) | Yesterday |
"""


@pytest.fixture
def source() -> AggregatorSource:
    return AggregatorSource(
        name="speedyapply-2027-SWE",
        url="https://raw.githubusercontent.com/speedyapply/2027-SWE-College-Jobs/main/README.md",
        batch_years=[2027, 2028, 2029],
    )


@pytest.mark.asyncio
async def test_aggregator_parses_table(source):
    scraper = AggregatorScraper(source)

    async with respx.mock:
        respx.get(source.url).respond(text=sample_markdown())
        jobs = [job async for job in scraper.fetch()]

    assert len(jobs) == 4
    assert jobs[0].company == "Google"
    assert jobs[0].title == "SWE Intern"
    assert jobs[0].url == "https://google.com/jobs"
    assert jobs[0].source_ats == "aggregator:speedyapply-2027-SWE"
    assert jobs[1].company == "Stripe"
    assert jobs[2].company == "Jane Street"
    assert jobs[3].company == "Meta"


@pytest.mark.asyncio
async def test_aggregator_relative_dates_become_iso(source):
    scraper = AggregatorScraper(source)

    async with respx.mock:
        respx.get(source.url).respond(text=sample_markdown())
        jobs = [job async for job in scraper.fetch()]

    # "2 days ago" -> date_posted 2 days before now; unknown dates stay None
    assert jobs[0].date_posted is not None
    parsed = datetime.strptime(jobs[0].date_posted, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert (datetime.now(timezone.utc) - parsed).days >= 2
    assert jobs[2].date_posted is not None  # "Just posted" -> today
    assert jobs[3].date_posted is not None  # "Yesterday" -> 1 day ago


@pytest.mark.asyncio
async def test_aggregator_handles_404(source):
    scraper = AggregatorScraper(source)

    async with respx.mock:
        respx.get(source.url).respond(status_code=404)
        jobs = [job async for job in scraper.fetch()]
    assert len(jobs) == 0
