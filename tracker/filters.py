import re
from datetime import datetime, timezone
from typing import Optional

from tracker.config import FiltersConfig
from tracker.models import RawJob

GRAD_YEAR_PATTERN = re.compile(
    r"(?:class\s+of\s+|batch\s+|graduat(?:ing|ion)\s+(?:year\s+)?|grad\s+year\s+)?"
    r"(20\d{2})",
    re.IGNORECASE,
)


def _list_match(text: str | None, keywords: list[str]) -> bool:
    if not text or not keywords:
        return False
    text_lower = text.lower()
    for kw in keywords:
        pattern = re.compile(r"\b" + re.escape(kw.lower()) + r"\b")
        if pattern.search(text_lower):
            return True
    return False


def _check_exclude(title: str, description: str | None, exclude: list[str]) -> bool:
    combined = title.lower()
    if description:
        combined += " " + description.lower()
    for kw in exclude:
        pattern = re.compile(r"\b" + re.escape(kw.lower()) + r"\b")
        if pattern.search(combined):
            return True
    return False


DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%d",
)


def parse_posted_date(date_posted: str | None) -> Optional[datetime]:
    """Parse a posting timestamp into an aware UTC datetime, or None if unparseable."""
    if not date_posted:
        return None
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(date_posted, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _check_max_age(date_posted: str | None, max_days: int) -> bool:
    if not date_posted or max_days <= 0:
        return True
    dt = parse_posted_date(date_posted)
    if dt is None:
        return True
    return (datetime.now(timezone.utc) - dt).days <= max_days


def _check_grad_year(title: str, description: str | None, allowed_years: list[Optional[int]]) -> bool:
    combined = title
    if description:
        combined += " " + description
    found_years = set()
    for match in GRAD_YEAR_PATTERN.finditer(combined):
        year = int(match.group(1))
        if 2020 <= year <= 2040:
            found_years.add(year)
    if not found_years:
        return None in allowed_years
    for y in found_years:
        if y in allowed_years:
            return True
    return False


def check_job_filters(job: RawJob, config: FiltersConfig, skip_location_filter: bool = False) -> tuple[bool, list[str]]:
    title = job.title or ""
    description = job.description or ""

    role_include = config.role_keywords.include
    role_exclude = config.role_keywords.exclude
    title_include = config.title_keywords.include
    title_exclude = config.title_keywords.exclude
    loc_include = config.locations.include
    loc_exclude = config.locations.exclude
    emp_include = config.employment_types.include
    emp_exclude = config.employment_types.exclude

    if role_exclude:
        combined = title.lower() + " " + description.lower()
        if _list_match(combined, role_exclude):
            return False, ["Excluded by role keyword"]

    if role_include:
        combined = title + " " + (description or "")
        if not _list_match(combined, role_include):
            return False, ["No matching role keyword"]

    if title_exclude:
        if _list_match(title, title_exclude):
            return False, ["Excluded by title keyword"]

    if title_include:
        if not _list_match(title, title_include):
            return False, ["No matching title keyword"]

    if loc_exclude and not skip_location_filter:
        if job.location and _list_match(job.location, loc_exclude):
            return False, ["Excluded by location"]

    if loc_include and not skip_location_filter:
        if job.location:
            if not _list_match(job.location, loc_include):
                return False, ["Location not in include list"]

    if emp_exclude:
        if job.employment_type and _list_match(job.employment_type, emp_exclude):
            return False, ["Excluded by employment type"]

    # ponytail: unknown employment_type passes (most ATS APIs omit it) — reject only on explicit mismatch
    if emp_include and job.employment_type and not _list_match(job.employment_type, emp_include):
        return False, ["Employment type not in include list"]

    if not _check_grad_year(title, description, config.allowed_grad_years):
        return False, ["Graduation year not in allowed list"]

    if not _check_max_age(job.date_posted, config.max_posting_age_days):
        return False, ["Posting exceeds max age"]

    return True, ["Passed all filters"]
