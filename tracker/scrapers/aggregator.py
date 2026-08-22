"""
Aggregator feed parser.

Pulls job listings from community-maintained GitHub markdown repositories
that aggregate internship postings across many companies.

Format: pipe-table markdown with variable columns (5 or 6):
    | Company | Position | Location | Link | Date |
    | Company | Position | Location | Salary | Link | Date |

Tagged as source_ats = "aggregator:<source_name>" for dedup.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import httpx

from tracker.config import AggregatorSource
from tracker.filters import GRAD_YEAR_PATTERN
from tracker.models import RawJob
from tracker.logger import get_logger

logger = get_logger()

LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
HTML_LINK_RE = re.compile(r'<a\s+href="([^"]+)"', re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
DATE_RE = re.compile(
    r"\b\d+\s*(?:days?\s*ago|hours?\s*ago|[hd])\b"
    r"|\b(?:just\s*posted|today|yesterday)\b",
    re.IGNORECASE,
)


def _strip_html(text: str) -> str:
    return HTML_TAG_RE.sub("", text).strip()


def _extract_url(cell: str) -> str:
    """Extract URL from markdown or HTML link."""
    md = LINK_RE.search(cell)
    if md:
        return md.group(2).strip()
    html = HTML_LINK_RE.search(cell)
    if html:
        return html.group(1).strip()
    return ""


def _days_ago(text: str) -> int | None:
    m = re.search(r"(\d+)\s*days?\s*ago", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*[hd]", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    if re.search(r"\bjust\s*posted\b|\btoday\b", text, re.IGNORECASE):
        return 0
    if re.search(r"\byesterday\b", text, re.IGNORECASE):
        return 1
    return None


def _parse_row(stripped: str) -> RawJob | None:
    """Parse a single pipe-delimited table row into a RawJob."""
    parts = [c.strip() for c in stripped.split("|")]
    parts = parts[1:-1] if len(parts) > 2 else parts
    if len(parts) < 5:
        return None

    company = _strip_html(parts[0])
    title = _strip_html(parts[1])
    location = _strip_html(parts[2])

    if len(parts) == 6:
        salary_or_link = parts[3]
        link_cell = parts[4]
        date_cell = parts[5]
        url = _extract_url(link_cell)
        if not url:
            url = _extract_url(salary_or_link)
    else:
        link_cell = parts[3]
        date_cell = parts[4]
        url = _extract_url(link_cell)

    # Convert relative dates ("2 days ago", "yesterday") to ISO so max-age filtering works
    days = _days_ago(_strip_html(date_cell))
    date_posted = (
        (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        if days is not None
        else None
    )

    return RawJob(
        company=company,
        title=title,
        location=location or None,
        url=url,
        description=None,
        employment_type=None,
        date_posted=date_posted,
        source_ats="",
    )


class AggregatorScraper:
    def __init__(self, source: AggregatorSource) -> None:
        self._source = source

    async def fetch(self) -> AsyncIterator[RawJob]:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(self._source.url)
                if resp.status_code == 404:
                    logger.warning(
                        "[Aggregator] Source %s returned 404", self._source.name
                    )
                    return
                resp.raise_for_status()
                text = resp.text
        except Exception as e:
            logger.error(
                "[Aggregator] Failed to fetch %s: %s", self._source.name, e
            )
            return

        lines = text.split("\n")
        in_table = False
        source_tag = f"aggregator:{self._source.name}"

        for line in lines:
            stripped = line.strip()

            if stripped.startswith("|---"):
                in_table = True
                continue

            if not in_table or not stripped.startswith("|"):
                if in_table and not stripped.startswith("|"):
                    in_table = False
                continue

            if not stripped or DATE_RE.search(stripped.split("|")[0] if "|" in stripped else ""):
                continue

            job = _parse_row(stripped)
            if not job:
                continue

            # batch_years: drop rows targeting grad years outside the configured set
            if self._source.batch_years:
                text = f"{job.title} {job.description or ''}"
                years = {int(m.group(1)) for m in GRAD_YEAR_PATTERN.finditer(text)}
                if years and not (years & set(self._source.batch_years)):
                    continue

            job.source_ats = source_tag
            yield job
