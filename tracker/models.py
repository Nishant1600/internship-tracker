from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class RawJob:
    company: str
    title: str
    location: Optional[str]
    url: str
    description: Optional[str]
    employment_type: Optional[str]
    date_posted: Optional[str]
    source_ats: str


@dataclass
class Job:
    id: Optional[int]
    company: str
    title: str
    location: Optional[str]
    url: str
    description: Optional[str]
    description_hash: str
    employment_type: Optional[str]
    date_posted: Optional[str]
    date_found: str
    date_last_seen: str
    match_score: Optional[int]
    match_reasons: Optional[str]
    notified_at: Optional[str]
    source_ats: str


@dataclass
class StructuredResume:
    name: str
    skills: list[str]
    education: list[str]
    work: list[str]
    projects: list[str]
    certifications: list[str]


@dataclass
class MatchResult:
    score: int
    reasons: list[str] = field(default_factory=list)
