import pytest

from tracker.models import Job
from tracker.notifiers.telegram import format_digest


def make_job(
    company: str = "Goldman Sachs",
    title: str = "Quantitative Research Intern",
    location: str | None = "Bangalore, India",
    url: str = "https://goldmansachs.com/jobs/1",
    notified: bool = False,
) -> Job:
    return Job(
        id=1,
        company=company,
        title=title,
        location=location,
        url=url,
        description=None,
        description_hash="abc123",
        employment_type="Intern",
        date_posted="2026-06-15",
        date_found="2026-07-05 10:00:00",
        date_last_seen="2026-07-05 10:00:00",
        notified_at="2026-07-05 10:00:00" if notified else None,
        source_ats="greenhouse",
    )


class TestFormatDigest:
    def test_digest_header(self):
        result = format_digest([], {}, max_jobs=25)
        assert "Internship Digest" in result
        assert "2026" in result or "2025" in result

    def test_jobs_displayed(self):
        jobs = [
            (make_job(company="A", title="Intern"), "easy"),
            (make_job(company="B", title="Intern"), "medium"),
        ]
        result = format_digest(jobs, {}, max_jobs=25)
        assert "B" in result
        assert "A" in result

    def test_run_summary(self):
        stats = {
            "total_scraped": 274,
            "passed_filters": 18,
            "new_today": 3,
            "failed": 2,
        }
        result = format_digest([], stats, max_jobs=25)
        assert "274 companies scraped" in result
        assert "18 jobs found" in result
        assert "2 failed" in result

    def test_no_failed_companies(self):
        stats = {"total_scraped": 10, "passed_filters": 5, "new_today": 2}
        result = format_digest([], stats, max_jobs=25)
        assert "failed" not in result

    def test_capped_at_max_jobs(self):
        jobs = [(make_job(company=f"C{i}", title="Intern"), "easy") for i in range(30)]
        result = format_digest(jobs, {}, max_jobs=10)
        assert result.count("http") <= 11

    def test_url_shown(self):
        job = (make_job(url="https://example.com/job"), "easy")
        result = format_digest([job], {}, max_jobs=25)
        assert "https://example.com/job" in result

    def test_tier_grouping(self):
        jobs = [
            (make_job(company="A", title="Intern 1"), "easy"),
            (make_job(company="B", title="Intern 2"), "easy"),
            (make_job(company="C", title="Intern 3"), "hard"),
        ]
        result = format_digest(jobs, {}, max_jobs=25)
        assert "Easy (2)" in result
        assert "Hard (1)" in result
