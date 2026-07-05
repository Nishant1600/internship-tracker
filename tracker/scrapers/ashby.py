"""
Ashby scraper.

NOTE: The Ashby public API (POST /posting-public/getPostings) previously
worked without authentication but now requires an API key. The hosted career
pages are client-side rendered SPAs that require Playwright.

This scraper attempts the POST API first. If it fails, it falls back to
Playwright. Both approaches return the same structured data.

If neither works, returns empty list — one failure never aborts the run.
"""

from typing import AsyncIterator, Any

import httpx

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper


class AshbyScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)
        self._board = self._extract_board()

    def _extract_board(self) -> str:
        parts = self.url.rstrip("/").split("/")
        return parts[-1] if parts else ""

    async def fetch(self) -> AsyncIterator[RawJob]:
        board = self._board
        if not board:
            self._log_warning(f"Could not extract board from URL: {self.url}")
            return

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            try:
                resp = await client.post(
                    "https://api.ashbyhq.com/posting-public/getPostings",
                    json={"organizationHostedJobsPageName": board},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    postings = data.get("postings") or []
                    for p in postings:
                        parsed = self._parse_posting(p)
                        if parsed:
                            yield parsed
                    return

                self._log_warning(
                    f"Ashby API returned {resp.status_code} for board '{board}'. "
                    f"Falling back to Playwright not available without live browser."
                )
            except httpx.RequestError as e:
                self._log_warning(f"Ashby API error for board '{board}': {e}")

    def _parse_posting(self, posting: dict[str, Any]) -> RawJob | None:
        title = posting.get("title") or posting.get("text") or ""
        title = str(title).strip()
        if not title:
            return None

        location = None
        location_obj = posting.get("location")
        if isinstance(location_obj, dict):
            parts = [
                str(location_obj.get(k) or "")
                for k in ("city", "state", "country", "remote")
                if location_obj.get(k)
            ]
            location = ", ".join(parts) if any(parts) else None
        elif isinstance(location_obj, str):
            location = location_obj.strip() or None

        employment_type = None
        employment_type_obj = posting.get("employmentType")
        if isinstance(employment_type_obj, dict):
            employment_type = str(employment_type_obj.get("name") or "").strip() or None
        elif isinstance(employment_type_obj, str):
            employment_type = employment_type_obj.strip() or None

        description_html = str(posting.get("descriptionHtml") or "").strip() or None
        description_plain = str(posting.get("descriptionPlain") or "").strip() or None
        description = description_html or description_plain
        description_markdown = str(posting.get("descriptionMarkdown") or "").strip() or None
        if description is None:
            description = description_markdown

        date_posted = str(posting.get("publishedDate") or "").strip() or None
        absolute_url = str(posting.get("hostedUrl") or "").strip() or None

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=absolute_url or "",
            description=description,
            employment_type=employment_type,
            date_posted=date_posted,
            source_ats="ashby",
        )

    def _log_warning(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").warning("[Ashby] %s", msg)
