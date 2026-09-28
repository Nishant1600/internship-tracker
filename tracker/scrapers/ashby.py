"""
Ashby scraper.

Primary: the unauthenticated public job-board feed
    GET https://api.ashbyhq.com/posting-api/job-board/<board>
which returns {"jobs": [...]}.

Fallback: the legacy POST posting-public/getPostings. It used to work without
authentication but now requires an API key (401 for anonymous callers), so it
only helps if the public feed disappears and the POST route is reopened.

If neither works, yields nothing — one failure never aborts the run.
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
            # Public job-board feed (no auth). Returns {"jobs": [...]}.
            try:
                resp = await client.get(
                    f"https://api.ashbyhq.com/posting-api/job-board/{board}"
                )
                if resp.status_code == 200:
                    for p in resp.json().get("jobs") or []:
                        parsed = self._parse_posting(p)
                        if parsed:
                            yield parsed
                    return
                status = resp.status_code
            except (httpx.RequestError, ValueError) as e:
                status = f"{type(e).__name__}: {e}"

            # Legacy POST endpoint: requires an API key now (401 for anonymous).
            try:
                resp = await client.post(
                    "https://api.ashbyhq.com/posting-public/getPostings",
                    json={"organizationHostedJobsPageName": board},
                )
                if resp.status_code == 200:
                    for p in resp.json().get("postings") or []:
                        parsed = self._parse_posting(p)
                        if parsed:
                            yield parsed
                    return
                self._log_warning(
                    f"Ashby GET returned {status}, POST returned {resp.status_code} "
                    f"for board '{board}' (Playwright fallback unavailable)."
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

        date_posted = str(
            posting.get("publishedAt") or posting.get("publishedDate") or ""
        ).strip() or None
        absolute_url = str(
            posting.get("jobUrl") or posting.get("hostedUrl") or ""
        ).strip() or None

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
