"""Regression tests for main.py orchestration (parallel tier runner, watchdog condition)."""
import asyncio

import pytest

import main
from tracker.config import AppConfig, CompanyConfig, ScraperConfig


def make_cfg(n: int = 4) -> AppConfig:
    return AppConfig(scraper=ScraperConfig(max_concurrency=n))


class FakeLogger:
    def warning(self, *a):
        pass

    def error(self, *a):
        pass

    def info(self, *a):
        pass


def api_company(name: str) -> CompanyConfig:
    return CompanyConfig(name=name, ats="greenhouse", url="https://x.com/boards/x/jobs")


def test_run_tier_parallel_pools(monkeypatch):
    calls = []

    async def fake_scrape(company, config, repo, logger):
        calls.append(company.name)
        await asyncio.sleep(0.01)
        return [f"job-{company.name}"], 10

    monkeypatch.setattr(main, "_scrape_company", fake_scrape)
    companies = [api_company(f"A{i}") for i in range(5)]
    companies.append(CompanyConfig(name="PW", ats="workday", url="https://x.com"))

    jobs, raw, failed = asyncio.run(main._run_tier(companies, make_cfg(), None, FakeLogger()))

    assert set(jobs) == {f"job-A{i}" for i in range(5)} | {"job-PW"}
    assert raw == 60
    assert failed == []
    assert sorted(calls) == sorted(["A0", "A1", "A2", "A3", "A4", "PW"])


def test_run_tier_browser_pool_is_smaller(monkeypatch):
    """Browser scrapers share a separate, tighter semaphore (memory-bound)."""
    pw_companies = [CompanyConfig(name=f"P{i}", ats="workday", url="https://x.com") for i in range(6)]
    state = {"inflight": 0, "peak": 0}

    async def slow(company, config, repo, logger):
        state["inflight"] += 1
        state["peak"] = max(state["peak"], state["inflight"])
        await asyncio.sleep(0.01)
        state["inflight"] -= 1
        return [], 1

    monkeypatch.setattr(main, "_scrape_company", slow)
    # force browser classification so the test doesn't depend on playwright being installed
    monkeypatch.setattr(main, "_is_playwright_scraper", lambda scraper: True)

    asyncio.run(main._run_tier(pw_companies, make_cfg(6), None, FakeLogger()))

    assert state["peak"] <= main._PLAYWRIGHT_CONCURRENCY


def test_run_tier_captures_failed_names(monkeypatch):
    async def boom(company, config, repo, logger):
        if company.name == "A0":
            raise RuntimeError("boom")
        return [], 1

    monkeypatch.setattr(main, "_scrape_company", boom)
    companies = [api_company(f"A{i}") for i in range(3)]

    jobs, raw, failed = asyncio.run(main._run_tier(companies, make_cfg(), None, FakeLogger()))

    assert failed == ["A0"]
    assert jobs == []


def test_run_tier_respects_max_concurrency(monkeypatch):
    state = {"inflight": 0, "peak": 0}

    async def slow(company, config, repo, logger):
        state["inflight"] += 1
        state["peak"] = max(state["peak"], state["inflight"])
        await asyncio.sleep(0.01)
        state["inflight"] -= 1
        return [], 1

    monkeypatch.setattr(main, "_scrape_company", slow)
    companies = [api_company(f"A{i}") for i in range(6)]

    asyncio.run(main._run_tier(companies, make_cfg(2), None, FakeLogger()))

    assert state["peak"] == 2


def test_is_dry_run():
    assert main._is_dry_run([{"raw": 0}, {"raw": 0}], 100) is True
    assert main._is_dry_run([{"raw": 0}, {"raw": 5}], 100) is False
    assert main._is_dry_run([], 0) is False


def test_check_config_valid(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
companies:
  easy:
    - {name: "A", ats: "greenhouse", url: "https://boards-api.greenhouse.io/v1/boards/a/jobs"}
    - {name: "B", ats: "html", url: "https://b.com/careers", css_selector: "div.job"}
"""
    )
    assert main.check_config(str(cfg)) == 0


def test_check_config_flags_errors_and_duplicates(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
companies:
  easy:
    - {name: "A", ats: "greenhouse", url: "https://x.com/boards/a/jobs"}
    - {name: "A", ats: "lever", url: "not-a-url"}
    - {name: "C", ats: "html", url: "https://c.com"}
"""
    )
    rc = main.check_config(str(cfg))
    assert rc == 1


def test_check_config_missing_file(tmp_path):
    assert main.check_config(str(tmp_path / "nope.yaml")) == 1
