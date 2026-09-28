"""Link health: probe every company URL and alert when a link stops working.

Snapshot-based: each run writes data/link_health.json, and only links whose
state *changed* since the previous run are reported — so a permanently blocked
host is a one-time finding, not daily spam. First run is a baseline (no alert
about pre-existing breakage, just the counts).

States: ok (<400) / blocked (401, 403, 429 — likely bot protection) / dead
(404, 5xx, DNS, timeout). ponytail: status-level check only; a 200 that serves
the wrong markup is caught by the pipeline's empty-result failures instead.

Plain HTTP probes lie for bot-protected sites (403/406 to httpx, 200 in a real
browser), so any non-ok URL whose scraper is Playwright-based gets one browser
confirmation before its state is recorded — only those pay the browser cost.

ponytail: known ceiling — a 200 with empty content (SmartRecruiters answers
200 for an unknown company slug) reads as ok; catching that means parsing the
response body per ATS, which the pipeline's empty-run watchdog already covers.
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

from tracker.logger import get_logger
from tracker.scrapers import get_scraper

logger = get_logger()

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "link_health.json"
PROBE_TIMEOUT = 20.0
PROBE_CONCURRENCY = 20
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def classify(status: int | None, error: str | None) -> str:
    if error or status is None:
        return "dead"
    if status < 400:
        return "ok"
    if status in (401, 403, 429):
        return "blocked"
    return "dead"


def diff_states(prev: dict[str, str], curr: dict[str, str]) -> tuple[list[str], list[str]]:
    """Return (newly broken, recovered) company names.

    Names absent from prev (baseline run, newly added company) are never
    alerted on — only ok -> broken counts as "stopped working".
    """
    newly_broken = [
        name for name, state in curr.items()
        if prev.get(name) == "ok" and state != "ok"
    ]
    recovered = [
        name for name, state in curr.items()
        if prev.get(name) in ("dead", "blocked") and state == "ok"
    ]
    return newly_broken, recovered


def suppress_for_outage(prev: dict[str, str], newly_broken: list[str]) -> bool:
    """True when failures look like a local outage instead of link rot.

    A mass ok -> dead flip in one run is almost always DNS/network trouble on
    this machine; alerting would flood Telegram now and again next run when
    everything "recovers".
    """
    prev_ok = sum(1 for s in prev.values() if s == "ok")
    return len(newly_broken) >= 5 and len(newly_broken) > 0.3 * max(prev_ok, 1)


async def probe_company(client: httpx.AsyncClient, record: dict) -> dict:
    status: int | None = None
    error: str | None = None
    try:
        resp = await client.get(record["url"], follow_redirects=True)
        status = resp.status_code
    except Exception as e:
        # nothing in a probe should escape: one malformed config URL or an
        # odd redirect must not kill the whole check (no snapshot, no alert)
        error = f"{type(e).__name__}: {str(e)[:120]}"
    return {
        **record,
        "status": status,
        "state": classify(status, error),
        "error": error,
    }


def _is_browser_scraper(company, scraper_cfg) -> bool:
    try:
        scraper = get_scraper(company, scraper_cfg)
    except Exception:
        return False
    mod = sys.modules.get(type(scraper).__module__)
    return bool(getattr(mod, "PLAYWRIGHT_AVAILABLE", False))


async def _confirm_with_browser(pending: list[dict], timeout: float) -> None:
    """Re-check non-ok URLs with a real browser (one shared browser, sequential)."""
    if not pending:
        return
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning(
            "Playwright unavailable; %d browser links left at HTTP status",
            len(pending),
        )
        return
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        try:
            context = await browser.new_context(user_agent=BROWSER_UA)
            for rec in pending:
                # one bad page must not abort the confirmation of the rest
                try:
                    page = await context.new_page()
                    try:
                        resp = await page.goto(
                            rec["url"], timeout=int(timeout * 1000), wait_until="domcontentloaded"
                        )
                        status = resp.status if resp else None
                    finally:
                        await page.close()
                    if status and status < 400:
                        rec.update(state="ok", status=status, error=None)
                    elif status:
                        rec.update(status=status, state=classify(status, None))
                except Exception as e:
                    rec["browser_error"] = str(e)[:120]
                    logger.warning(
                        "Browser confirm failed for %s: %s", rec["name"], rec["browser_error"]
                    )
        finally:
            await browser.close()


async def check_links(config, timeout: float = PROBE_TIMEOUT) -> dict:
    """Probe every configured company URL (config: AppConfig). Returns the report."""
    entries = [
        (tier, c)
        for tier, group in _by_tier(config.companies)
        for c in group
    ]
    records = [
        {"name": c.name, "tier": tier, "ats": c.ats, "url": c.url}
        for tier, c in entries
    ]
    sem = asyncio.Semaphore(PROBE_CONCURRENCY)

    # one pooled client for all probes (connection reuse instead of 259 handshakes)
    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": BROWSER_UA},
        verify=True,
    ) as client:
        async def _one(rec: dict) -> dict:
            async with sem:
                return await probe_company(client, rec)

        results = list(await asyncio.gather(*(_one(r) for r in records)))

    pending = [
        rec
        for rec, (tier, c) in zip(results, entries)
        if rec["state"] != "ok" and _is_browser_scraper(c, config.scraper)
    ]
    if pending:
        logger.info(
            "Confirming %d non-ok browser links with Playwright: %s",
            len(pending), ", ".join(r["name"] for r in pending),
        )
    await _confirm_with_browser(pending, timeout)

    checked = {r["name"]: r for r in results}
    counts = {"ok": 0, "blocked": 0, "dead": 0}
    for rec in results:
        counts[rec["state"]] += 1
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(results),
        "counts": counts,
        "results": checked,
    }


def _by_tier(companies) -> list[tuple[str, list]]:
    # Accept either TieredCompanies (by_tier) or a plain list of (tier, group).
    if hasattr(companies, "by_tier"):
        return companies.by_tier()
    return list(companies)


def load_snapshot(path: Path = DATA_FILE) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or not isinstance(data.get("results"), dict):
        return {}
    return {
        name: rec.get("state")
        for name, rec in data["results"].items()
        if isinstance(rec, dict)
    }


def save_snapshot(report: dict, path: Path = DATA_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, indent=1), encoding="utf-8")
    tmp.replace(path)  # atomic: a kill mid-write must not corrupt the baseline


def format_alert(report: dict, newly_broken: list[str], recovered: list[str]) -> list[str]:
    """Body lines for TelegramNotifier.send_alert (header added by caller)."""
    counts = report["counts"]
    lines = [
        f"{report['total']} checked · {counts['ok']} ok · "
        f"{counts['dead']} dead · {counts['blocked']} blocked",
        "",
        "Stopped working:",
    ]
    results = report["results"]
    for name in newly_broken:
        rec = results[name]
        detail = f"HTTP {rec['status']}" if rec["status"] else rec["error"]
        lines.append(f"  ✗ {name} ({rec['tier']}) — {detail}")
        lines.append(f"    {rec['url']}")
    if recovered:
        lines.append("")
        lines.append("Recovered:")
        for name in recovered:
            lines.append(f"  ✓ {name} ({results[name]['tier']})")
    return lines
