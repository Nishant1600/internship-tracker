"""
Custom API scraper.

A generic HTTP/JSON scraper for career sites that expose REST APIs
(Accenture, EPAM, Jane Street, etc.) or embed job data in HTML pages
(Google).

BEST-EFFORT ONLY — each API has a unique response structure.
"""

import logging
import re
from typing import AsyncIterator, Any

import httpx

from tracker.config import CompanyConfig, ScraperConfig
from tracker.models import RawJob
from tracker.scrapers.base import BaseScraper

logger = logging.getLogger("tracker")


def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    return str(val)


class CustomAPIScraper(BaseScraper):
    def __init__(self, company: CompanyConfig, config: ScraperConfig) -> None:
        super().__init__(company.name, company.url, config)

    async def fetch(self) -> AsyncIterator[RawJob]:
        try:
            async with httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
                follow_redirects=True,
                headers={
                    "Accept": "application/json, text/html",
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                },
            ) as client:
                # Google Careers uses pagination via start parameter
                start = 0
                page_size = 20
                max_pages = 50  # Safety limit
                seen_ids = set()

                for _ in range(max_pages):
                    url = self.url
                    if "google.com" in self.url:
                        url = f"{self.url}?start={start}"

                    resp = await client.get(url)
                    if resp.status_code == 404:
                        logger.warning("[CustomAPI] 404 for %s", self.company)
                        return
                    resp.raise_for_status()

                    content_type = resp.headers.get("content-type", "")
                    if "json" in content_type:
                        data = resp.json()
                        jobs = self._extract_jobs(data)
                    elif "html" in content_type:
                        jobs = self._extract_jobs_from_html(resp.text)
                    else:
                        logger.warning(
                            "[CustomAPI] %s returned unexpected content-type: %s",
                            self.company, content_type,
                        )
                        return

                    if not jobs:
                        break

                    new_jobs = 0
                    for item in jobs:
                        job_id = item.get("jobId") or item.get("id") or item.get("title")
                        if job_id in seen_ids:
                            continue
                        seen_ids.add(job_id)
                        parsed = self._parse_job(item)
                        if parsed:
                            new_jobs += 1
                            yield parsed

                    if new_jobs == 0 and start > 0:
                        break

                    start += page_size
                    if len(jobs) < page_size:
                        break

        except Exception as e:
            logger.error("[CustomAPI] Failed for %s: %s", self.company, e)

    def _extract_jobs_from_html(self, html: str) -> list[dict]:
        """Extract job data from HTML pages with embedded JSON (e.g., Google Careers)."""
        jobs = []
        try:
            # Find the ds:1 callback (Google's job data format)
            marker = "AF_initDataCallback({key: 'ds:1'"
            idx = html.find(marker)
            if idx < 0:
                return jobs
            
            # Find the data: part
            data_start = html.find("data:", idx)
            if data_start < 0:
                return jobs
            
            # Find the matching closing bracket by counting brackets
            depth = 0
            pos = data_start + 5  # skip 'data:'
            started = False
            while pos < len(html):
                if html[pos] == "[":
                    depth += 1
                    started = True
                elif html[pos] == "]":
                    depth -= 1
                    if started and depth == 0:
                        break
                pos += 1
            
            data_str = html[data_start + 5:pos + 1]
            
            # Extract job entries: [job_id, title, url, ...]
            job_pattern = r'\["(\d{15,})","([^"]{3,120})","https://www\.google\.com'
            for job_id, title in re.findall(job_pattern, data_str):
                jobs.append({
                    "title": title,
                    "jobId": job_id,
                    "url": f"https://www.google.com/about/careers/applications/jobs/results/{job_id}",
                })
        except Exception as e:
            logger.debug("[CustomAPI] Failed to parse HTML job data: %s", e)
        return jobs

    def _extract_jobs(self, data: Any) -> list[dict]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in (
                "jobs", "data", "results", "items",
                "requisitions", "jobRequisitions", "jobPostings",
                "opportunities", "openings", "positions",
            ):
                if key in data and isinstance(data[key], list):
                    return data[key]
                if key in data and isinstance(data[key], dict):
                    return self._extract_jobs(data[key])
        return []

    def _parse_job(self, item: dict) -> RawJob | None:
        title = _safe_str(
            item.get("title") or item.get("jobTitle") or item.get("name") or
            item.get("position") or item.get("positionTitle") or ""
        ).strip()
        if not title:
            return None

        location = _safe_str(
            item.get("location") or item.get("jobLocation") or
            item.get("primaryLocation") or item.get("city") or ""
        ).strip() or None

        description = _safe_str(
            item.get("description") or item.get("jobDescription") or
            item.get("descriptionPlain") or ""
        ).strip() or None

        url = _safe_str(
            item.get("url") or item.get("jobUrl") or item.get("applyUrl") or
            item.get("absolute_url") or item.get("hostedUrl") or ""
        ).strip()

        if not url:
            job_id = item.get("jobId") or item.get("id") or item.get("requisitionId")
            if job_id:
                url = f"{self.url.rstrip('/')}/jobs/{job_id}"

        date_posted = _safe_str(
            item.get("datePosted") or item.get("postedDate") or
            item.get("createdAt") or item.get("dateCreated") or ""
        ).strip() or None

        employment_type = _safe_str(
            item.get("employmentType") or item.get("type") or ""
        ).strip() or None

        return RawJob(
            company=self.company,
            title=title,
            location=location,
            url=url,
            description=description,
            employment_type=employment_type,
            date_posted=date_posted,
            source_ats="custom-api",
        )
