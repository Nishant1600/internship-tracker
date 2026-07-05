import json

import pytest

from tracker.models import Job
from tracker.notifiers.telegram import format_digest


def make_job(
    company: str = "Goldman Sachs",
    title: str = "Quantitative Research Intern",
    location: str | None = "Bangalore, India",
    match_score: int | None = 82,
    match_reasons: list[str] | None = None,
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
        match_score=match_score,
        match_reasons=json.dumps(match_reasons) if match_reasons else None,
        notified_at="2026-07-05 10:00:00" if notified else None,
        source_ats="greenhouse",
    )


class TestFormatDigest:
    def test_digest_header(self):
        result = format_digest([], None, {}, max_jobs=25)
        assert "📅 Daily Internship Digest" in result
        assert "Jul 2026" in result or "Jul 2025" in result

    def test_resume_score_included(self):
        result = format_digest([], 74, {}, max_jobs=25)
        assert "Resume Quality Score: 74/100" in result

    def test_resume_score_omitted_when_none(self):
        result = format_digest([], None, {}, max_jobs=25)
        assert "Resume Quality Score" not in result

    def test_jobs_displayed_sorted(self):
        jobs = [
            make_job(company="A", title="Intern", match_score=50),
            make_job(company="B", title="Intern", match_score=90),
        ]
        result = format_digest(jobs, None, {}, max_jobs=25)
        assert "B" in result
        assert "A" in result

    def test_matched_skills_shown(self):
        reasons = ["python", "statistics", "risk analytics"]
        job = make_job(match_reasons=reasons)
        result = format_digest([job], None, {}, max_jobs=25)
        assert "✅ Matched: Python" in result
        assert "Statistics" in result
        assert "Risk analytics" in result

    def test_run_summary(self):
        stats = {
            "total_scraped": 47,
            "passed_filters": 18,
            "above_threshold": 12,
            "new_today": 3,
            "failed": 2,
        }
        result = format_digest([], None, stats, max_jobs=25)
        assert "47 companies scraped" in result
        assert "18 passed filters" in result
        assert "12 above score threshold" in result
        assert "3 new today" in result
        assert "2 companies failed" in result

    def test_no_failed_companies(self):
        stats = {"total_scraped": 10, "passed_filters": 5, "new_today": 2}
        result = format_digest([], None, stats, max_jobs=25)
        assert "⚠️" not in result

    def test_capped_at_max_jobs(self):
        jobs = [make_job(company=f"C{i}", title="Intern", match_score=50) for i in range(30)]
        result = format_digest(jobs, None, {}, max_jobs=10)
        assert result.count("📍") == 10

    def test_no_location_fallback(self):
        job = make_job(location=None)
        result = format_digest([job], None, {}, max_jobs=25)
        assert "Location not specified" in result

    def test_no_match_score_shown(self):
        job = make_job(match_score=None, match_reasons=None)
        result = format_digest([job], None, {}, max_jobs=25)
        assert "🎯" not in result
