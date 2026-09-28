from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator


def _validate_hhmm(v: str) -> str:
    parts = v.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time format '{v}'. Use HH:MM (24h).")
    h, m = parts
    if not (h.isdigit() and m.isdigit()):
        raise ValueError(f"Invalid time format '{v}'. Use HH:MM (24h).")
    if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
        raise ValueError(f"Time '{v}' out of range. Hours 0-23, minutes 0-59.")
    return v


class ScheduleConfig(BaseModel):
    time: str = "08:00"
    timezone: str = "Asia/Kolkata"

    @field_validator("time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        return _validate_hhmm(v)


class LinkCheckConfig(BaseModel):
    """Daily probe of every company URL; Telegram alert on state changes."""
    enabled: bool = True
    time: str = "07:30"

    # a typo here must fail at config load, not int(hour) inside the daemon
    @field_validator("time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        return _validate_hhmm(v)


class DatabaseConfig(BaseModel):
    path: str = "./data/jobs.db"
    prune_days: int = 90  # notified jobs not seen this long are deleted; 0 disables


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "./logs/tracker.log"


class ScraperConfig(BaseModel):
    timeout_seconds: int = 15
    retry_count: int = 3
    retry_backoff_seconds: int = 5
    headless: bool = True
    max_concurrency: int = 6  # parallel JSON-API scrapers per tier; Playwright always sequential


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


class TelegramConfig(BaseModel):
    enabled: bool = False
    max_jobs_per_digest: int = 25
    send_if_empty: bool = False
    heartbeat: bool = True  # compact end-of-run summary ping after every run


class FeaturesConfig(BaseModel):
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
    company_id: Optional[str] = None
    domain: Optional[str] = None
    account_name: Optional[str] = None
    org_id: Optional[str] = None
    skip_location_filter: bool = False

    @field_validator("ats")
    @classmethod
    def validate_ats(cls, v: str) -> str:
        allowed = {
            "greenhouse", "lever", "ashby", "workday",
            "smartrecruiters", "bamboohr", "icims", "html",
            "aggregator", "direct", "tcs",
            "successfactors", "phenompeople", "custom-portal", "custom-api",
            "google", "openai", "notion", "netflix", "meta", "microsoft", "block", "jobvite", "qburst", "swiggy", "zwayam", "linkedin", "kula", "turbohire", "payu", "walmart", "atlassian", "eightfold", "sap", "oracle", "ibm", "cisco", "texasinstruments", "qualcomm", "dell", "netapp", "nutanix", "honeywell", "moengage", "morganstanley", "goldmansachs",             "americanexpress", "hsbc", "jpmorgan", "bnymellon", "talentlink", "amd", "arista", "hpe",
        }
        if v not in allowed:
            raise ValueError(f"Unknown ATS type '{v}'. Allowed: {', '.join(sorted(allowed))}")
        return v


class TieredCompanies(BaseModel):
    """Holds companies grouped by difficulty tier."""
    tiers: dict[str, list[CompanyConfig]] = Field(default_factory=dict)

    def flat(self) -> list[CompanyConfig]:
        """Return all companies as a flat list."""
        result = []
        for tier_companies in self.tiers.values():
            result.extend(tier_companies)
        return result

    def by_tier(self) -> list[tuple[str, list[CompanyConfig]]]:
        """Return companies grouped by tier in order."""
        return [(name, companies) for name, companies in self.tiers.items()]

    @property
    def total(self) -> int:
        return sum(len(c) for c in self.tiers.values())


class AppConfig(BaseModel):
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    link_check: LinkCheckConfig = Field(default_factory=LinkCheckConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    scraper: ScraperConfig = Field(default_factory=ScraperConfig)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    aggregator_feeds: AggregatorFeedConfig = Field(default_factory=AggregatorFeedConfig)
    companies: TieredCompanies = Field(default_factory=TieredCompanies)


def load_config(path: str | Path) -> AppConfig:
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"Config file is empty or invalid YAML: {path}")

    companies_raw = raw.get("companies", {})
    if isinstance(companies_raw, list):
        raw["companies"] = {"tiers": {"default": companies_raw}}
    elif isinstance(companies_raw, dict):
        raw["companies"] = {"tiers": companies_raw}

    return AppConfig(**raw)
