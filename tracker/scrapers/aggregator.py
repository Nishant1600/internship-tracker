"""
Aggregator feed parser.

Pulls job listings from community-maintained GitHub markdown repositories
that aggregate internship postings across many companies.

Format: standard pipe-table markdown:
    | Company | Role | Location | Application/Link | Date Posted |
    |---------|------|----------|-----------------|-------------|
    | Google  | SWE Intern | ... | [Apply](url) | 2 days ago |

Tagged as source_ats = "aggregator:<source_name>" for dedup.
"""

import re
from typing import AsyncIterator

import httpx

from tracker.config import AggregatorSource
from tracker.models import RawJob
from tracker.logger import get_logger

logger = get_logger()

TABLE_ROW_RE = re.compile(
    r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.*?)\s*\|"
)
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


def _extract_link(cell: str) -> tuple[str, str]:
    """Extract text and URL from a markdown link cell."""
    match = LINK_RE.search(cell)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return cell.strip(), ""


def _days_ago(text: str) -> int | None:
    """Parse 'X days ago' style text into number of days."""
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

        for line in lines:
            stripped = line.strip()

            if stripped.startswith("|---"):
                in_table = True
                continue

            if not in_table or not stripped.startswith("|"):
                continue

            match = TABLE_ROW_RE.match(stripped)
            if not match:
                continue

            company = match.group(1).strip()
            role = match.group(2).strip()
            location = match.group(3).strip()
            link_cell = match.group(4).strip()
            date_cell = match.group(5).strip()

            title, url = _extract_link(role)
            if not title:
                title = role
            if not url:
                _, url = _extract_link(link_cell)
                if not url:
                    _, url = _extract_link(role)

            date_age = _days_ago(date_cell)
            source_tag = f"aggregator:{self._source.name}"

            yield RawJob(
                company=company,
                title=title,
                location=location or None,
                url=url,
                description=None,
                employment_type=None,
                date_posted=None,
                source_ats=source_tag,
            )
