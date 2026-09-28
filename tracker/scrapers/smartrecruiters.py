from typing import AsyncIterator, Any

import httpx

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper


class SmartRecruitersScraper(BaseScraper):
    """
    SmartRecruiters Public API.
    GET https://api.smartrecruiters.com/v1/companies/{slug}/postings

    The slug is extracted from the configured URL.
    """

    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)
        self._slug = self._extract_slug()

    def _extract_slug(self) -> str:
        parts = self.url.rstrip("/").split("/")
        if len(parts) >= 2 and parts[-1] == "postings":
            return parts[-2] if len(parts) >= 2 else ""
        return parts[-1] if parts else ""

    async def fetch(self) -> AsyncIterator[RawJob]:
        slug = self._slug
        if not slug:
            self._log_warning(f"Could not extract slug from URL: {self.url}")
            return

        api_url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            try:
                resp = await client.get(api_url)
                if resp.status_code == 404:
                    self._log_warning(f"Board returned 404 for {slug}")
                    return
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                self._log_error(f"HTTP {e.response.status_code} for {slug}: {e}")
                return

            content = data.get("content") or []
            for posting in content:
                parsed = self._parse_posting(posting)
                if parsed:
                    yield parsed

    def _parse_posting(self, posting: dict[str, Any]) -> RawJob | None:
        title = str(posting.get("name") or "").strip()
        if not title:
            return None

        location_obj = posting.get("location") or {}
        location_parts = [
            str(location_obj.get(k) or "")
            for k in ("city", "state", "country", "remote")
            if location_obj.get(k)
        ]
        location = ", ".join(location_parts) if any(location_parts) else None

        employment_type = None
        type_obj = posting.get("typeOfEmployment") or {}
        if isinstance(type_obj, dict):
            employment_type = str(type_obj.get("label") or "").strip() or None
        elif isinstance(type_obj, str):
            employment_type = type_obj.strip() or None

        description = str(posting.get("jobAd") or posting.get("description") or "").strip() or None
        description_sections = posting.get("jobAdSections") or {}
        if not description and description_sections:
            sections_text = []
            for section in description_sections.values():
                if isinstance(section, dict):
                    text = str(section.get("text") or section.get("content") or "")
                    if text.strip():
                        sections_text.append(text.strip())
                elif isinstance(section, str):
                    sections_text.append(section.strip())
            description = "\n\n".join(sections_text) if sections_text else None

        date_posted = str(posting.get("postedDate") or posting.get("createdDate") or "").strip() or None

        # The public API sets neither `url` nor `applyUrl` — build the public job
        # page from company identifier + posting id, fall back to the API permalink.
        absolute_url = str(posting.get("url") or posting.get("applyUrl") or "").strip()
        if not absolute_url:
            company_obj = posting.get("company")
            ident = str(company_obj.get("identifier") or "").strip() if isinstance(company_obj, dict) else ""
            pid = str(posting.get("id") or "").strip()
            if ident and pid:
                absolute_url = f"https://jobs.smartrecruiters.com/{ident}/{pid}"
        if not absolute_url:
            absolute_url = str(posting.get("ref") or "").strip()

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=absolute_url or "",
            description=description,
            employment_type=employment_type,
            date_posted=date_posted,
            source_ats="smartrecruiters",
        )

    def _log_warning(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").warning("[SmartRecruiters] %s", msg)

    def _log_error(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").error("[SmartRecruiters] %s", msg)
