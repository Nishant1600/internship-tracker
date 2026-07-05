import pytest

from tracker.matching.job_matcher import JobMatcher, extract_keywords, extract_required_skills
from tracker.matching.resume_fallback import HEMANG_RESUME_FALLBACK
from tracker.models import RawJob, StructuredResume


def make_job(
    title: str = "Software Engineer Intern",
    description: str | None = "Python intern role",
    location: str | None = "Bangalore",
) -> RawJob:
    return RawJob(
        company="Test",
        title=title,
        location=location,
        url="https://test.com/job/1",
        description=description,
        employment_type="Intern",
        date_posted="2026-06-15T10:00:00Z",
        source_ats="greenhouse",
    )


class TestExtractKeywords:
    def test_empty_text(self):
        assert extract_keywords(None) == set()
        assert extract_keywords("") == set()

    def test_known_tech_terms(self):
        result = extract_keywords("Python, TypeScript, React, and AWS")
        assert "python" in result
        assert "typescript" in result
        assert "react" in result
        assert "aws" in result

    def test_case_insensitive(self):
        result = extract_keywords("PYTHON, Machine Learning, KUBERNETES")
        assert "python" in result
        assert "machine learning" in result
        assert "kubernetes" in result

    def test_years_extracted(self):
        result = extract_keywords("Graduating in 2028, class of 2027")
        assert "2028" in result
        assert "2027" in result


class TestExtractRequiredSkills:
    def test_from_title_and_description(self):
        job = make_job(
            title="Python Developer",
            description="Looking for Python and Django expertise",
        )
        skills = extract_required_skills(job)
        assert "python" in skills
        assert "django" in skills

    def test_no_skills_found(self):
        job = make_job(
            title="Random Job",
            description="Some generic description without any tech terms",
        )
        skills = extract_required_skills(job)
        assert len(skills) == 0


class TestJobMatcher:
    def test_perfect_match(self):
        resume = StructuredResume(
            name="Test",
            skills=["Python", "Django", "AWS"],
            education=[],
            work=[],
            projects=[],
            certifications=[],
        )
        matcher = JobMatcher()
        job = make_job(
            title="Python/Django Developer",
            description="Python, Django, AWS required",
        )
        result = matcher.score(job, resume)
        assert result.score == 100
        assert "python" in result.reasons
        assert "django" in result.reasons

    def test_partial_match(self):
        resume = StructuredResume(
            name="Test",
            skills=["Python", "Java", "C++"],
            education=[],
            work=[],
            projects=[],
            certifications=[],
        )
        matcher = JobMatcher()
        job = make_job(
            title="Full Stack Developer",
            description="Python, JavaScript, React, AWS, Docker",
        )
        result = matcher.score(job, resume)
        assert 0 < result.score < 100
        assert "python" in result.reasons

    def test_no_match(self):
        resume = StructuredResume(
            name="Test",
            skills=["Python"],
            education=[],
            work=[],
            projects=[],
            certifications=[],
        )
        matcher = JobMatcher()
        job = make_job(
            title="Dentist",
            description="Dental surgery required",
        )
        result = matcher.score(job, resume)
        assert result.score == 0

    def test_match_from_projects(self):
        resume = StructuredResume(
            name="Test",
            skills=["Python"],
            education=[],
            work=[],
            projects=["Built trading system with Python and C++"],
            certifications=[],
        )
        matcher = JobMatcher()
        job = make_job(
            title="Trading Intern",
            description="C++ programming required",
        )
        result = matcher.score(job, resume)
        assert "c++" in result.reasons

    def test_resume_fallback_realistic(self):
        matcher = JobMatcher()
        job = make_job(
            title="Quantitative Research Intern",
            description="Python, statistics, probability, risk analytics",
        )
        result = matcher.score(job, HEMANG_RESUME_FALLBACK)
        assert result.score > 0
        assert "python" in result.reasons

    def test_no_description_only_title(self):
        resume = StructuredResume(
            name="Test",
            skills=["Python"],
            education=[],
            work=[],
            projects=[],
            certifications=[],
        )
        matcher = JobMatcher()
        job = make_job(title="Python Developer", description=None)
        result = matcher.score(job, resume)
        assert result.score > 0
