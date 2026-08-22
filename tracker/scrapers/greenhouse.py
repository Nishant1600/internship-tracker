from typing import AsyncIterator, Any

import httpx

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper


def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float)):
        return str(val)
    return str(val)


class GreenhouseScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        url = self.url
        # Extract board name from URL — format: .../boards/{board}/jobs...
        parts = url.rstrip("/").split("/")
        # Try to find 'boards' in the path and take the next segment
        board = ""
        for i, part in enumerate(parts):
            if part == "boards" and i + 1 < len(parts):
                board = parts[i + 1].split("?")[0]
                break
        if not board:
            # Fallback: try last segment (e.g. .../phonepe or .../boards/razorpay/jobs)
            last = parts[-1].split("?")[0]
            # If last segment is 'jobs' or empty, use second-to-last
            if last in ("jobs", ""):
                board = parts[-2].split("?")[0] if len(parts) >= 2 else ""
            else:
                board = last
        # Use the JSON API
        api_url = f"https://api.greenhouse.io/v1/boards/{board}/jobs"
        # content=true includes job descriptions + metadata so keyword/grad-year filters see full text
        params: dict[str, str | int] = {"content": "true"}
        page = 1

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds, follow_redirects=True) as client:
            while True:
                params["page"] = page
                try:
                    resp = await client.get(api_url, params=params)
                    if resp.status_code == 404:
                        self._log_skip(f"Board returned 404 for {self.company}")
                        return
                    resp.raise_for_status()
                    data = resp.json()
                except httpx.HTTPStatusError as e:
                    self._log_error(f"HTTP {e.response.status_code} for {self.company}: {e}")
                    return

                jobs = data.get("jobs", [])
                for job_data in jobs:
                    parsed = self._parse_job(job_data)
                    if parsed:
                        yield parsed

                self._log_info(f"Page {page}: {len(jobs)} jobs for {self.company}")

                meta = data.get("meta", {})
                total_pages = meta.get("total_pages", 1)
                if page >= total_pages:
                    break
                page += 1

    def _parse_job(self, job_data: dict[str, Any]) -> RawJob | None:
        title = (job_data.get("title") or "").strip()
        if not title:
            return None

        location_raw = job_data.get("location") or {}
        location_parts = []
        if isinstance(location_raw, dict):
            name = location_raw.get("name")
            if name:
                location_parts.append(name)
            loc_meta = location_raw.get("location", {})
            if isinstance(loc_meta, dict):
                for field in ("city", "state", "country"):
                    val = loc_meta.get(field)
                    if val:
                        location_parts.append(val)
        location = ", ".join(location_parts) if location_parts else None

        absolute_url = job_data.get("absolute_url") or ""
        metadata = job_data.get("metadata") or []

        employment_type = None
        for meta_item in metadata:
            if isinstance(meta_item, dict):
                name = _safe_str(meta_item.get("name")).lower()
                value = _safe_str(meta_item.get("value")).lower()
                if "employment" in name or "type" in name:
                    employment_type = value
                    break

        date_posted = (job_data.get("updated_at") or "").strip() or None
        description = (job_data.get("content") or "").strip() or None

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=absolute_url,
            description=description,
            employment_type=employment_type,
            date_posted=date_posted,
            source_ats="greenhouse",
        )

    def _log_skip(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").warning("[Greenhouse] %s", msg)

    def _log_error(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").error("[Greenhouse] %s", msg)

    def _log_info(self, msg: str) -> None:
        import logging
        logging.getLogger("tracker").info("[Greenhouse] %s", msg)
