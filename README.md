# Personal Internship Alert System

A single-user Python application that scrapes career pages of 330+ companies, detects new internship postings, filters them against configurable preferences, and sends a Telegram digest twice daily.

## Quick Start

```bash
# Clone and set up
cd internship-tracker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Configure
cp .env.example .env
# Edit .env with your BOT_TOKEN and CHAT_ID

# Run once
python main.py --run-now

# Validate config without scraping
python main.py --check-config

# Run as daemon (APScheduler, runs daily at configured time)
python main.py --daemon
```

## Configuration

Everything user-tunable lives in `config.yaml`:
- **Schedule**: time and timezone for daily digest
- **Scrapers**: timeout, retry count, headless mode, `max_concurrency` (parallel JSON-API scrapers per tier; browser scrapers share a separate pool of 2)
- **Database**: `path`, `prune_days` (delete notified jobs not seen this long; 0 disables)
- **Filters**: role keywords, title keywords, locations, employment types, graduation years, max posting age
- **Telegram**: max jobs per digest, empty digest toggle, heartbeat ping toggle
- **Company List**: 330+ companies pre-populated across ATS types (Greenhouse, Lever, Ashby, SmartRecruiters, BambooHR, Workday, HTML fallback)

### Adding a Company

```yaml
companies:
  - name: "Company Name"
    ats: "greenhouse"          # greenhouse | lever | ashby | smartrecruiters | bamboohr | workday | icims | html
    url: "https://..."         # career page or API URL
    css_selector: "div.job"   # only needed for html type
```

### Filter Toggling

Set any filter's include/exclude list to empty `[]` to disable it:

```yaml
filters:
  role_keywords:
    include: []                # disable role keyword filtering
  locations:
    include: []                # accept all locations
```

## Telegram Setup

1. Talk to [@BotFather](https://t.me/BotFather) on Telegram, create a bot, get the token
2. Find your chat ID (message your bot, visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`)
3. Set `BOT_TOKEN` and `CHAT_ID` in `.env` (never in config.yaml)

## Running on a Schedule

### APScheduler (default daemon mode)
```bash
python main.py --daemon
```

### Cron
```
0 2 * * * cd /path/to/internship-tracker && .venv/bin/python main.py --run-now >> logs/cron.log 2>&1
```

### GitHub Actions
`.github/workflows/internship-tracker.yml` runs tests then the pipeline twice daily (06:00 and 18:00 IST) via `schedule`, with `BOT_TOKEN` and `CHAT_ID` repo secrets. Trigger manually with `workflow_dispatch`.

Reliability features:
- The SQLite DB in `data/` persists between runs via the actions cache, so dedup works across runs.
- If the job crashes, you get a Telegram message with the run link; `logs/` is uploaded as a 7-day artifact on every run.
- If scrapers return zero raw jobs across all companies (likely blocked), you get a forced ⚠️ warning even with `send_if_empty: false`.
- Tier digests are capped at `max_jobs_per_digest` and list failed company names so dead boards can be removed from config.
- A compact ✅ heartbeat (companies · new jobs · failed · duration) is sent after every run; disable with `telegram.heartbeat: false`.

## Project Structure

```
internship-tracker/
  main.py                    # Entry point: --run-now, --daemon
  config.yaml                # User configuration (single source of truth)
  .env.example               # Secret keys template
  .gitignore
  Dockerfile
  docker-compose.yml

  tracker/
    config.py                # Pydantic v2 config loader
    models.py                # Dataclasses: RawJob, Job, StructuredResume, MatchResult
    database.py              # SQLite repository
    filters.py               # Keyword/rule-based filtering
    dedup.py                 # Hash-based dedup check
    scheduler.py             # APScheduler setup

    scrapers/
      base.py                # BaseScraper ABC
      greenhouse.py          # Greenhouse JSON API
      lever.py               # Lever JSON API
      ashby.py               # Ashby JSON API (best-effort)
      smartrecruiters.py     # SmartRecruiters JSON API
      bamboohr.py            # BambooHR JSON API
      workday.py             # Workday Playwright (best-effort)
      icims.py               # iCIMS HTML fallback (best-effort)
      html_fallback.py       # Generic Playwright + CSS selector
      aggregator.py          # GitHub markdown table parser

    notifiers/
      base.py                # Notifier ABC
      telegram.py            # Telegram digest formatter + sender

  tests/
    fixtures/                # Saved API responses for mock tests
    test_*.py                # Pytest files (no live HTTP)
```

## Testing

```bash
pytest tests/ -v
```

All tests use saved fixtures via `respx` — no live HTTP calls. The `unittest.mock.patch` approach is used for subprocess-based components.

## Troubleshooting

| Symptom | Likely Cause |
|---------|-------------|
| Lever boards all 404 | Lever public API is legacy/deprecated; most boards return 404. Scraper logs and skips. |
| Workday returns no jobs | Workday DOM varies by tenant; Playwright approach is best-effort. |
| Telegram not sending | `BOT_TOKEN` or `CHAT_ID` not set in `.env`. |
| Slow pipeline | Retries on 404/500; reduce `retry_count` or `timeout_seconds` in config. |

## Adding a New ATS Scraper

1. Create `tracker/scrapers/<name>.py` implementing `BaseScraper`
2. Implement `async def fetch(self) -> AsyncIterator[RawJob]`
3. Save a fixture to `tests/fixtures/<name>_fixture.json`
4. Write test in `tests/test_scraper_<name>.py`
5. Register in `tracker/scrapers/__init__.py`
6. Add to config.yaml

## Supported ATS Platforms

| ATS | Method | Status |
|---|---|---|
| Greenhouse | Public JSON API | Stable |
| Lever | Public JSON API | Legacy (most boards 404) |
| Ashby | POST API / Playwright | API requires key; best-effort |
| SmartRecruiters | Public JSON API | Stable |
| BambooHR | Public JSON API | Stable |
| Workday | Playwright | Best-effort, tenant-specific |
| iCIMS | HTML fallback | Best-effort |
| Generic HTML | Playwright + CSS selector | Fragile |
