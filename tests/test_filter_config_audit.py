"""Filter audit against the REAL config.yaml (not a synthetic config).

Green tests: behaviour that is correct and must stay correct.
XFail tests: real bugs found by the audit — each one reproduces against
live-scraped jobs and fails today, so it flips to XPASS when fixed.
"""
import pytest

from tracker.config import load_config
from tracker.filters import check_job_filters, _list_match, _location_list_match
from tracker.models import RawJob

CFG = load_config("config.yaml")
F = CFG.filters

# A typical real internship JD (paraphrased from live Greenhouse postings).
TYPICAL_JD = (
    "As a Software Engineering Intern you will work with your manager and team lead "
    "to ship features. You will learn how staff engineers review code, participate in "
    "design reviews, and collaborate with the principal architect. "
    "Requirements: pursuing BS/MS, graduating 2027."
)


def job(title, location="Bengaluru, India", description=None, employment_type=None,
        date_posted=None):
    return RawJob(
        company="TestCorp", title=title, location=location, url="https://x.test/1",
        description=description, employment_type=employment_type,
        date_posted=date_posted, source_ats="greenhouse",
    )


# ---------------------------------------------------------------- green: correct


class TestWorkingBehaviour:
    @pytest.mark.parametrize("loc", [
        "Bengaluru, Karnataka, India", "Bangalore, India", "Pune, Maharashtra",
        "Hyderabad, Telangana", "Gurugram", "Noida, Uttar Pradesh",
        "Chennai, Tamil Nadu", "Kolkata", "Ahmedabad, India", "IN", "Bengaluru, IN",
    ])
    def test_india_locations_pass(self, loc):
        ok, reasons = check_job_filters(job("Software Engineer Intern", loc), F)
        assert ok, reasons

    @pytest.mark.parametrize("loc", [
        "New York, United States", "London, United Kingdom", "Toronto, Canada",
    ])
    def test_overseas_locations_rejected(self, loc):
        ok, reasons = check_job_filters(job("Software Engineer Intern", loc), F)
        assert not ok and reasons[0] == "Location not in include list"

    @pytest.mark.parametrize("loc", ["US only", "EU only", "UK only", "USA only"])
    def test_explicit_us_only_excluded(self, loc):
        ok, reasons = check_job_filters(job("Software Engineer Intern", loc), F)
        assert not ok and reasons[0] == "Excluded by location"

    def test_country_code_in_not_confused_with_english_in(self):
        # "IN" must match only as a delimited token, never the word "in"
        assert _location_list_match("Located in San Francisco", F.locations.include) is False
        assert _location_list_match("Bengaluru, IN", F.locations.include) is True

    def test_missing_location_fails_closed(self):
        for loc in (None, "   "):
            ok, reasons = check_job_filters(job("Software Engineer Intern", loc), F)
            assert not ok and reasons[0] == "Missing location"

    def test_grad_year_2026_rejected_2027_allowed(self):
        ok, _ = check_job_filters(
            job("Software Engineer Intern", description="Class of 2026"), F)
        assert not ok
        ok, _ = check_job_filters(
            job("Software Engineer Intern", description="Class of 2027"), F)
        assert ok

    def test_stale_posting_rejected(self):
        ok, reasons = check_job_filters(
            job("Software Engineer Intern", date_posted="2020-01-01T00:00:00Z"), F)
        assert not ok and reasons[0] == "Posting exceeds max age"

    def test_non_intern_full_time_title_rejected(self):
        ok, _ = check_job_filters(job("Engineering Manager, Platform"), F)
        assert not ok

    def test_unknown_employment_type_passes(self):
        # most ATS APIs omit it; unknown must not be rejected
        ok, _ = check_job_filters(job("Software Engineer Intern", employment_type=None), F)
        assert ok


# ---------------------------------------------- bugs fixed in this audit


class TestFixedBugs:
    def test_role_exclude_ignores_description(self):
        # "manager"/"lead"/"staff"/"principal" appear in every intern JD's prose
        j = job("Software Engineer Intern", description=TYPICAL_JD)
        ok, reasons = check_job_filters(j, F)
        assert ok, reasons

    def test_role_exclude_still_fires_on_title(self):
        ok, reasons = check_job_filters(
            job("Senior Software Engineer Intern", description=TYPICAL_JD), F)
        assert not ok and reasons[0] == "Excluded by role keyword"

    def test_software_engineering_intern_matches_title_keyword(self):
        # 'software engineer' must stem-match 'software engineering'
        assert _list_match("Software Engineering Intern", F.title_keywords.include, prefix=True)

    def test_software_engineering_intern_reaches_pipeline(self):
        ok, reasons = check_job_filters(
            job("Software Engineering Intern", description=TYPICAL_JD), F)
        assert ok, reasons

    def test_full_time_typed_internship_passes(self):
        # employment_types.include is empty in config: metadata can't kill an internship
        j = job("Software Engineer Intern", description="intern 2027",
                employment_type="full time")
        ok, reasons = check_job_filters(j, F)
        assert ok, reasons

    def test_us_remote_does_not_pass_india_filter(self):
        assert check_job_filters(job("Software Engineer Intern", "US Remote"), F)[0] is False
        assert check_job_filters(job("Software Engineer Intern", "Remote, Europe"), F)[0] is False
        assert check_job_filters(job("Software Engineer Intern", "Remote"), F)[0] is True

    def test_grad_year_ignores_years_in_urls(self):
        j = job("Software Engineer Intern",
                description="See https://example.com/files/2024-08/pay.pdf for details")
        assert check_job_filters(j, F)[0] is True

    def test_prose_words_do_not_signal_internship(self):
        # role include searches the JD, so generic words ('challenging', 'virtual
        # teams') admit full-time jobs — they must not be in the include list
        j = job("Software Engineer", description="A challenging role on a virtual-first team")
        ok, reasons = check_job_filters(j, F)
        assert not ok and reasons[0] == "No matching role keyword"
