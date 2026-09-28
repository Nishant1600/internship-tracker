import pytest
from datetime import datetime, timezone, timedelta

from tracker.config import FiltersConfig, FilterList
from tracker.filters import check_job_filters
from tracker.models import RawJob


def make_job(
    company: str = "TestCorp",
    title: str = "Software Engineer Intern",
    location: str | None = "Bangalore, India",
    description: str | None = "Python intern role for 2028 batch",
    employment_type: str | None = "Intern",
    date_posted: str | None = "2026-06-15T10:00:00Z",
) -> RawJob:
    return RawJob(
        company=company,
        title=title,
        location=location,
        url="https://test.com/job/1",
        description=description,
        employment_type=employment_type,
        date_posted=date_posted,
        source_ats="greenhouse",
    )


def make_config(**kwargs) -> FiltersConfig:
    defaults = {
        "role_keywords": FilterList(include=["intern", "internship"], exclude=["senior"]),
        "title_keywords": FilterList(include=["software engineer"], exclude=[]),
        "locations": FilterList(include=["india", "bangalore"], exclude=[]),
        "employment_types": FilterList(include=["intern"], exclude=[]),
        "allowed_grad_years": [2027, 2028, 2029, None],
        "max_posting_age_days": 0,
    }
    defaults.update(kwargs)
    return FiltersConfig(**defaults)


class TestRoleKeywordFilter:
    def test_passes_with_matching_role_keyword(self):
        cfg = make_config()
        job = make_job(title="Software Engineer Intern")
        ok, reasons = check_job_filters(job, cfg)
        assert ok is True
        assert "No matching role keyword" not in str(reasons)

    def test_drops_when_no_role_keyword_match(self):
        cfg = make_config(role_keywords=FilterList(include=["intern"]))
        job = make_job(title="Software Engineer", description="Full time role")
        ok, _ = check_job_filters(job, cfg)
        assert ok is False

    def test_role_exclude_takes_priority(self):
        cfg = make_config(role_keywords=FilterList(include=["intern"], exclude=["senior"]))
        job = make_job(title="Senior Software Engineer Intern")
        ok, _ = check_job_filters(job, cfg)
        assert ok is False

    def test_passes_when_role_keywords_empty(self):
        cfg = make_config(
            role_keywords=FilterList(include=[], exclude=[]),
            title_keywords=FilterList(include=[], exclude=[]),
        )
        job = make_job(title="SWE Intern 2028")
        ok, _ = check_job_filters(job, cfg)
        assert ok is True

    def test_passes_with_role_keyword_in_description(self):
        cfg = make_config(role_keywords=FilterList(include=["co-op"]))
        job = make_job(title="Software Engineer", description="Co-op opportunity for students")
        ok, _ = check_job_filters(job, cfg)
        assert ok is True


class TestTitleKeywordFilter:
    def test_passes_with_matching_title(self):
        cfg = make_config()
        job = make_job(title="Software Engineer Intern")
        ok, _ = check_job_filters(job, cfg)
        assert ok is True

    def test_drops_when_title_does_not_match(self):
        cfg = make_config(title_keywords=FilterList(include=["quantitative", "quant"]))
        job = make_job(title="Marketing Intern")
        ok, _ = check_job_filters(job, cfg)
        assert ok is False

    def test_passes_when_title_keywords_empty(self):
        cfg = make_config(title_keywords=FilterList(include=[], exclude=[]))
        job = make_job(title="Any Random Job")
        ok, _ = check_job_filters(job, cfg)
        assert ok is True


class TestLocationFilter:
    def test_passes_with_matching_location(self):
        cfg = make_config()
        job = make_job(location="Bangalore, India")
        ok, _ = check_job_filters(job, cfg)
        assert ok is True

    def test_drops_when_location_excluded(self):
        cfg = make_config(locations=FilterList(include=["india"], exclude=["us only"]))
        job = make_job(location="US only")
        ok, _ = check_job_filters(job, cfg)
        assert ok is False

    def test_passes_when_locations_empty(self):
        cfg = make_config(locations=FilterList(include=[], exclude=[]))
        job = make_job(location="Anywhere")
        ok, _ = check_job_filters(job, cfg)
        assert ok is True

    def test_drops_when_location_not_in_include(self):
        cfg = make_config(locations=FilterList(include=["india", "remote"]))
        job = make_job(location="San Francisco, CA")
        ok, reasons = check_job_filters(job, cfg)
        assert ok is False
        assert "Location not in include list" in reasons


class TestEmploymentTypeFilter:
    def test_passes_with_matching_type(self):
        cfg = make_config()
        job = make_job(employment_type="Intern")
        ok, _ = check_job_filters(job, cfg)
        assert ok is True

    def test_drops_when_excluded(self):
        cfg = make_config(employment_types=FilterList(include=["intern"], exclude=["full-time"]))
        job = make_job(employment_type="Full-Time", title="SWE Intern")
        ok, _ = check_job_filters(job, cfg)
        assert ok is False

    def test_passes_when_empty(self):
        cfg = make_config(employment_types=FilterList(include=[], exclude=[]))
        job = make_job(employment_type="Full-Time")
        ok, _ = check_job_filters(job, cfg)
        assert ok is True

    def test_rejects_when_type_not_in_include(self):
        cfg = make_config(employment_types=FilterList(include=["intern"], exclude=[]))
        job = make_job(employment_type="Contract")
        ok, reasons = check_job_filters(job, cfg)
        assert ok is False
        assert "Employment type not in include list" in reasons

    def test_passes_when_type_unknown(self):
        # Most ATS APIs (e.g. Greenhouse boards) omit employment type entirely;
        # unknown must not be rejected when an include list is set.
        cfg = make_config(employment_types=FilterList(include=["intern"], exclude=[]))
        job = make_job(employment_type=None)
        ok, _ = check_job_filters(job, cfg)
        assert ok is True


class TestGradYearFilter:
    def test_passes_allowed_year(self):
        cfg = make_config()
        job = make_job(description="Internship for 2028 batch")
        ok, _ = check_job_filters(job, cfg)
        assert ok is True

    def test_drops_unallowed_year(self):
        cfg = make_config(allowed_grad_years=[2027, 2028, 2029, None])
        job = make_job(description="Class of 2026")
        ok, _ = check_job_filters(job, cfg)
        assert ok is False

    def test_passes_no_year_mentioned(self):
        cfg = make_config(allowed_grad_years=[2027, 2028, 2029, None])
        job = make_job(description="Great internship opportunity")
        ok, _ = check_job_filters(job, cfg)
        assert ok is True

    def test_passes_multiple_years(self):
        cfg = make_config(allowed_grad_years=[2027, 2028, 2029, None])
        job = make_job(description="Graduation year 2027 or 2028")
        ok, _ = check_job_filters(job, cfg)
        assert ok is True


class TestMaxAgeFilter:
    def test_passes_recent_posting(self):
        cfg = make_config(max_posting_age_days=30)
        recent_date = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        job = make_job(date_posted=recent_date)
        ok, _ = check_job_filters(job, cfg)
        assert ok is True

    def test_drops_old_posting(self):
        cfg = make_config(max_posting_age_days=7)
        job = make_job(date_posted="2026-01-01T10:00:00Z")
        ok, _ = check_job_filters(job, cfg)
        assert ok is False

    def test_passes_no_date_posted(self):
        cfg = make_config(max_posting_age_days=30)
        job = make_job(date_posted=None)
        ok, _ = check_job_filters(job, cfg)
        assert ok is True

    def test_passes_when_max_age_is_zero(self):
        cfg = make_config(max_posting_age_days=0)
        job = make_job(date_posted="2020-01-01T10:00:00Z")
        ok, _ = check_job_filters(job, cfg)
        assert ok is True


class TestEdgeCases:
    def test_missing_location_rejected_when_include_set(self):
        cfg = make_config()
        job = make_job(location=None)
        ok, reasons = check_job_filters(job, cfg)
        assert ok is False
        assert "Missing location" in reasons

    def test_empty_location_rejected_when_include_set(self):
        cfg = make_config()
        job = make_job(location="   ")
        ok, reasons = check_job_filters(job, cfg)
        assert ok is False
        assert "Missing location" in reasons

    def test_missing_location_passes_when_include_empty(self):
        cfg = make_config(locations=FilterList(include=[], exclude=[]))
        job = make_job(location=None)
        ok, _ = check_job_filters(job, cfg)
        assert ok is True

    def test_missing_location_passes_when_skip_flag(self):
        cfg = make_config()
        job = make_job(location=None)
        ok, _ = check_job_filters(job, cfg, skip_location_filter=True)
        assert ok is True

    def test_country_code_in_only_as_token(self):
        # "IN" alone or "Bengaluru, IN" — not the English word "in"
        cfg = make_config(locations=FilterList(include=["india", "in"], exclude=[]))
        assert check_job_filters(make_job(location="IN"), cfg)[0] is True
        assert check_job_filters(make_job(location="Bengaluru, IN"), cfg)[0] is True
        # English "in" must not satisfy the include list
        cfg_no_in = make_config(locations=FilterList(include=["in"], exclude=[]))
        ok, reasons = check_job_filters(make_job(location="Located in San Francisco"), cfg_no_in)
        assert ok is False
        assert "Location not in include list" in reasons

    def test_us_remote_rejected_by_remote_keyword(self):
        # "Remote" alone passes, but a token outside the include vocabulary must not.
        cfg = make_config(locations=FilterList(include=["india", "remote"], exclude=[]))
        assert check_job_filters(make_job(location="US Remote"), cfg)[0] is False
        assert check_job_filters(make_job(location="Remote, Europe"), cfg)[0] is False
        assert check_job_filters(make_job(location="Remote"), cfg)[0] is True
        assert check_job_filters(make_job(location="Remote, India"), cfg)[0] is True

    def test_empty_description(self):
        cfg = make_config()
        job = make_job(description=None)
        ok, _ = check_job_filters(job, cfg)
        assert ok is True

    def test_all_filters_empty_pass_everything(self):
        cfg = FiltersConfig(
            role_keywords=FilterList(include=[], exclude=[]),
            title_keywords=FilterList(include=[], exclude=[]),
            locations=FilterList(include=[], exclude=[]),
            employment_types=FilterList(include=[], exclude=[]),
            allowed_grad_years=[None],
            max_posting_age_days=0,
        )
        job = make_job(
            title="CEO", location="Mars", employment_type="Full-Time",
            description="Generic description without year",
        )
        ok, _ = check_job_filters(job, cfg)
        assert ok is True

    def test_collects_filter_reasons(self):
        cfg = FiltersConfig(
            role_keywords=FilterList(include=["intern"], exclude=[]),
            title_keywords=FilterList(include=["software"], exclude=[]),
            locations=FilterList(include=["remote"], exclude=[]),
            employment_types=FilterList(include=["intern"], exclude=[]),
            allowed_grad_years=[2027, 2028, 2029, None],
            max_posting_age_days=30,
        )
        job = make_job(
            title="Software Engineer Intern",
            location="Remote",
            employment_type="Contract",
        )
        ok, reasons = check_job_filters(job, cfg)
        assert ok is False
        assert "Employment type not in include list" in str(reasons)
