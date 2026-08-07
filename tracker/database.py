import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tracker.models import Job, RawJob

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    company           TEXT NOT NULL,
    title             TEXT NOT NULL,
    location          TEXT,
    url               TEXT NOT NULL,
    description       TEXT,
    description_hash  TEXT NOT NULL UNIQUE,
    employment_type   TEXT,
    date_posted       TEXT,
    date_found        TEXT NOT NULL,
    date_last_seen    TEXT NOT NULL,
    notified_at       TEXT,
    source_ats        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_hash ON jobs(description_hash);
CREATE INDEX IF NOT EXISTS idx_jobs_notified ON jobs(notified_at);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
"""


def compute_hash(company: str, title: str, url: str) -> str:
    return hashlib.sha256(
        f"{company}|{title}|{url}".encode("utf-8")
    ).hexdigest()


class JobRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path).resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            company=row["company"],
            title=row["title"],
            location=row["location"],
            url=row["url"],
            description=row["description"],
            description_hash=row["description_hash"],
            employment_type=row["employment_type"],
            date_posted=row["date_posted"],
            date_found=row["date_found"],
            date_last_seen=row["date_last_seen"],
            notified_at=row["notified_at"],
            source_ats=row["source_ats"],
        )

    def upsert(self, job: RawJob) -> Optional[Job]:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        desc_hash = compute_hash(job.company, job.title, job.url)
        existing = self.find_by_hash(desc_hash)
        if existing:
            self._conn.execute(
                "UPDATE jobs SET date_last_seen = ?, location = ?, description = ?, "
                "employment_type = ?, date_posted = ? WHERE id = ?",
                (
                    now,
                    job.location,
                    job.description,
                    job.employment_type,
                    job.date_posted,
                    existing.id,
                ),
            )
            self._conn.commit()
            return self.find_by_hash(desc_hash)
        cursor = self._conn.execute(
            "INSERT INTO jobs (company, title, location, url, description, "
            "description_hash, employment_type, date_posted, date_found, "
            "date_last_seen, source_ats) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job.company,
                job.title,
                job.location,
                job.url,
                job.description,
                desc_hash,
                job.employment_type,
                job.date_posted,
                now,
                now,
                job.source_ats,
            ),
        )
        self._conn.commit()
        return self.get_by_id(cursor.lastrowid)

    def find_by_hash(self, desc_hash: str) -> Optional[Job]:
        cursor = self._conn.execute(
            "SELECT * FROM jobs WHERE description_hash = ?", (desc_hash,)
        )
        row = cursor.fetchone()
        return self._row_to_job(row) if row else None

    def get_by_id(self, job_id: int) -> Optional[Job]:
        cursor = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        return self._row_to_job(row) if row else None

    def is_seen(self, job: RawJob) -> bool:
        desc_hash = compute_hash(job.company, job.title, job.url)
        existing = self.find_by_hash(desc_hash)
        return existing is not None

    def is_notified(self, job: RawJob) -> bool:
        desc_hash = compute_hash(job.company, job.title, job.url)
        existing = self.find_by_hash(desc_hash)
        return existing is not None and existing.notified_at is not None

    def mark_notified(self, job_id: int) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self._conn.execute(
            "UPDATE jobs SET notified_at = ? WHERE id = ?", (now, job_id)
        )
        self._conn.commit()

    def get_unnotified(self) -> list[Job]:
        cursor = self._conn.execute(
            "SELECT * FROM jobs WHERE notified_at IS NULL"
        )
        return [self._row_to_job(row) for row in cursor.fetchall()]

    def get_all(self) -> list[Job]:
        cursor = self._conn.execute("SELECT * FROM jobs ORDER BY date_found DESC")
        return [self._row_to_job(row) for row in cursor.fetchall()]

    def count(self) -> int:
        cursor = self._conn.execute("SELECT COUNT(*) FROM jobs")
        return cursor.fetchone()[0]
