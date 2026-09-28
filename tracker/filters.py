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


def _list_match(text: str | None, keywords: list[str], *, prefix: bool = False) -> bool:
    """Word-boundary keyword match. prefix=True drops the trailing boundary so
    stems match their derivations ('software engineer' -> 'software engineering')."""
    if not text or not keywords:
        return False
    text_lower = text.lower()
    for kw in keywords:
        # prefix only helps multi-word stems ("software engineer" -> engineering);
        # single words keep both boundaries so \bai misses "Air"
        suffix = "" if (prefix and " " in kw) else r"\b"
        pattern = re.compile(r"\b" + re.escape(kw.lower()) + suffix)
        if pattern.search(text_lower):
            return True
    return False


# ponytail: English "in" vs country code "IN" — match codes only as delimited tokens
_LOCATION_TOKEN_KEYS = frozenset({"in", "ind"})


def _location_token_match(text: str, keyword: str) -> bool:
    """Match keyword as a comma/space-delimited token, or the whole string."""
    kw = keyword.lower()
    if kw not in _LOCATION_TOKEN_KEYS:
        return bool(re.search(r"\b" + re.escape(kw) + r"\b", text.lower()))
    parts = [p.strip() for p in re.split(r"[,/;|\-–—]+", text.lower()) if p.strip()]
    return any(p == kw for p in parts)


def _location_list_match(text: str | None, keywords: list[str]) -> bool:
    if not text or not keywords:
        return False
    return any(_location_token_match(text, kw) for kw in keywords)


# ponytail: these pass anywhere on their own — 'US Remote' / 'Remote, Europe' must not
_GENERIC_LOCATION_KEYS = frozenset({"remote", "hybrid", "wfh", "work from home", "anywhere", "global"})


def _location_accept(text: str | None, keywords: list[str]) -> bool:
    """True when the location satisfies the include list.

    A specific keyword (country/city/state) matches anywhere in the string. Generic
    remote/hybrid keywords only pass when every delimited token is itself in the
    include vocabulary, so 'US Remote' is rejected while bare 'Remote' passes.
    """
    if not text or not text.strip() or not keywords:
        return False
    specific = [k for k in keywords if k.lower() not in _GENERIC_LOCATION_KEYS]
    if _location_list_match(text, specific):
        return True
    generic = [k for k in keywords if k.lower() in _GENERIC_LOCATION_KEYS]
    if not _location_list_match(text, generic):
        return False
    vocab = {k.lower() for k in keywords}
    parts = [p.strip() for p in re.split(r"[,/;|()]+", text.lower()) if p.strip()]
    return bool(parts) and all(p in vocab for p in parts)


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


URL_RE = re.compile(r"https?://\S+")


def _check_grad_year(title: str, description: str | None, allowed_years: list[Optional[int]]) -> bool:
    # no year configured (all null) means "no graduation-year restriction"
    real_years = [y for y in allowed_years if y is not None]
    if not real_years:
        return True
    combined = title
    if description:
        combined += " " + description
    # ponytail: drop URLs — most stray years come from links ('.../2024-08/file.pdf')
    combined = URL_RE.sub(" ", combined)
    # ponytail: ignore years that predate any plausible graduating class
    floor = min(real_years) - 1
    found_years = set()
    for match in GRAD_YEAR_PATTERN.finditer(combined):
        year = int(match.group(1))
        if year > 2040:
            continue
        if year < floor:
            # grad-context year below the cohort floor ("Class of 2025") is a
            # real mismatch; a bare year is noise (founding dates, ranges)
            if match.group(0) != match.group(1):
                return False
            continue
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
        # ponytail: excludes are role-level signals ('senior', 'manager', 'lead') —
        # match the title only; internship JDs mention every one of them in prose.
        if _list_match(title, role_exclude):
            return False, ["Excluded by role keyword"]

    if role_include:
        combined = title + " " + (description or "")
        if not _list_match(combined, role_include):
            return False, ["No matching role keyword"]

    if title_exclude:
        if _list_match(title, title_exclude):
            return False, ["Excluded by title keyword"]

    if title_include:
        if not _list_match(title, title_include, prefix=True):
            return False, ["No matching title keyword"]

    if loc_exclude and not skip_location_filter:
        if job.location and _location_list_match(job.location, loc_exclude):
            return False, ["Excluded by location"]

    if loc_include and not skip_location_filter:
        # Fail closed: an include list is meaningless if missing location bypasses it.
        if not _location_accept(job.location, loc_include):
            if not (job.location and job.location.strip()):
                return False, ["Missing location"]
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
