from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator


class ScheduleConfig(BaseModel):
    time: str = "08:00"
    timezone: str = "Asia/Kolkata"

    @field_validator("time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid time format '{v}'. Use HH:MM (24h).")
        h, m = parts
        if not (h.isdigit() and m.isdigit()):
            raise ValueError(f"Invalid time format '{v}'. Use HH:MM (24h).")
        if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
            raise ValueError(f"Time '{v}' out of range. Hours 0-23, minutes 0-59.")
        return v


class DatabaseConfig(BaseModel):
    path: str = "./data/jobs.db"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "./logs/tracker.log"


class ScraperConfig(BaseModel):
    timeout_seconds: int = 15
    retry_count: int = 3
    retry_backoff_seconds: int = 5
    headless: bool = True


class FilterList(BaseModel):
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


class FiltersConfig(BaseModel):
    role_keywords: FilterList = Field(default_factory=FilterList)
    title_keywords: FilterList = Field(default_factory=FilterList)
    locations: FilterList = Field(default_factory=FilterList)
    employment_types: FilterList = Field(default_factory=FilterList)
    allowed_grad_years: list[Optional[int]] = Field(default_factory=lambda: [None])
    max_posting_age_days: int = 30
    minimum_match_score: int = 0


class HiringAgentConfig(BaseModel):
    enabled: bool = False
    repo_path: str = "../hiring-agent-main"
    python_path: str = "../hiring-agent-main/.venv/bin/python"
    resume_path: str = "./data/resume.pdf"
    rerun_on_resume_change: bool = True
    cache_dir: str = "./data/hiring_agent_cache"
    llm_backend: str = "gemini"
    ollama_base_url: str = "http://localhost:11434"

    @field_validator("llm_backend")
    @classmethod
    def validate_backend(cls, v: str) -> str:
        if v not in ("gemini", "ollama"):
            raise ValueError(f"llm_backend must be 'gemini' or 'ollama', got '{v}'")
        return v


class TelegramConfig(BaseModel):
    enabled: bool = False
    max_jobs_per_digest: int = 25
    send_if_empty: bool = False


class FeaturesConfig(BaseModel):
    hiring_agent_scoring: bool = True
    dedup_notifications: bool = True
    track_seen_only: bool = False


class AggregatorSource(BaseModel):
    name: str
    url: str
    batch_years: list[int] = Field(default_factory=list)


class AggregatorFeedConfig(BaseModel):
    enabled: bool = False
    max_posting_age_days: int = 3
    sources: list[AggregatorSource] = Field(default_factory=list)


class CompanyConfig(BaseModel):
    name: str
    ats: str
    url: str
    css_selector: Optional[str] = None

    @field_validator("ats")
    @classmethod
    def validate_ats(cls, v: str) -> str:
        allowed = {
            "greenhouse", "lever", "ashby", "workday",
            "smartrecruiters", "bamboohr", "icims", "html",
            "aggregator", "direct",
        }
        if v not in allowed:
            raise ValueError(f"Unknown ATS type '{v}'. Allowed: {', '.join(sorted(allowed))}")
        return v


class AppConfig(BaseModel):
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    scraper: ScraperConfig = Field(default_factory=ScraperConfig)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    hiring_agent: HiringAgentConfig = Field(default_factory=HiringAgentConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    aggregator_feeds: AggregatorFeedConfig = Field(default_factory=AggregatorFeedConfig)
    companies: list[CompanyConfig] = Field(default_factory=list)


def load_config(path: str | Path) -> AppConfig:
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"Config file is empty or invalid YAML: {path}")
    return AppConfig(**raw)
