import httpx
import pytest
import respx

from tracker.config import AppConfig, CompanyConfig, TieredCompanies
from tracker.link_health import (
    check_links,
    classify,
    diff_states,
    format_alert,
    load_snapshot,
    probe_company,
    save_snapshot,
    suppress_for_outage,
)


def test_classify_states():
    assert classify(200, None) == "ok"
    assert classify(301, None) == "ok"
    assert classify(404, None) == "dead"
    assert classify(500, None) == "dead"
    assert classify(403, None) == "blocked"
    assert classify(429, None) == "blocked"
    assert classify(None, "ConnectError: boom") == "dead"
    assert classify(200, "boom") == "dead"


def test_diff_alerts_only_state_changes():
    prev = {"a": "ok", "b": "ok", "c": "dead", "d": "blocked"}
    curr = {"a": "dead", "b": "ok", "c": "ok", "d": "blocked"}
    newly_broken, recovered = diff_states(prev, curr)
    assert newly_broken == ["a"]
    assert recovered == ["c"]


def test_diff_baseline_and_new_companies_are_silent():
    # no snapshot (first run) and brand-new company: never reported as "stopped working"
    assert diff_states({}, {"a": "dead"}) == ([], [])
    assert diff_states({"a": "ok"}, {"a": "ok", "new": "dead"}) == ([], [])


def test_format_alert_lists_broken_with_url():
    report = {
        "total": 3,
        "counts": {"ok": 1, "dead": 1, "blocked": 1},
        "results": {
            "Wise": {"tier": "medium-hard", "state": "dead", "status": 404,
                     "error": None, "url": "https://example.com/jobs"},
            "Circle": {"tier": "medium-hard", "state": "blocked", "status": 403,
                       "error": None, "url": "https://example.com/c"},
            "Miro": {"tier": "medium-hard", "state": "ok", "status": 200,
                     "error": None, "url": "https://example.com/m"},
        },
    }
    lines = format_alert(report, ["Wise", "Circle"], ["Miro"])
    text = "\n".join(lines)
    assert "1 ok · 1 dead · 1 blocked" in text
    assert "✗ Wise (medium-hard) — HTTP 404" in text
    assert "https://example.com/jobs" in text
    assert "✓ Miro" in text


def test_snapshot_roundtrip(tmp_path):
    path = tmp_path / "link_health.json"
    report = {
        "checked_at": "2026-09-28T00:00:00+00:00",
        "total": 1,
        "counts": {"ok": 1, "dead": 0, "blocked": 0},
        "results": {"Miro": {"name": "Miro", "state": "ok", "status": 200,
                             "error": None, "url": "https://example.com"}},
    }
    save_snapshot(report, path)
    assert load_snapshot(path) == {"Miro": "ok"}
    # corrupt/missing file degrades to empty baseline instead of raising
    path.write_text("{not json", encoding="utf-8")
    assert load_snapshot(path) == {}
    assert load_snapshot(tmp_path / "nope.json") == {}


def test_alert_fits_telegram_limit_when_split():
    from tracker.notifiers.telegram import TELEGRAM_MAX_LEN, _split_message

    # worst case: every company dead at once
    report = {
        "total": 259,
        "counts": {"ok": 0, "dead": 259, "blocked": 0},
        "results": {
            f"Company {i}": {
                "tier": "medium-hard", "state": "dead", "status": 404,
                "error": None, "url": f"https://example.com/{i}",
            }
            for i in range(259)
        },
    }
    messages = _split_message(
        "🔗 Link health alert", format_alert(report, list(report["results"]), [])
    )
    assert messages, "alert must not be dropped"
    assert all(len(m) <= TELEGRAM_MAX_LEN for m in messages)


def test_suppress_for_outage():
    prev_ok = {f"c{i}": "ok" for i in range(100)}
    assert suppress_for_outage(prev_ok, [f"c{i}" for i in range(60)]) is True
    assert suppress_for_outage(prev_ok, [f"c{i}" for i in range(3)]) is False
    # few failures but everything was already broken: not an outage flip
    assert suppress_for_outage({"a": "dead"}, ["a"]) is False


def test_load_snapshot_survives_wrong_shapes(tmp_path):
    path = tmp_path / "link_health.json"
    for junk in ("[]", "null", '{"results": {"X": "ok"}}', '{"results": {"X": 5}}'):
        path.write_text(junk, encoding="utf-8")
        load_snapshot(path)  # must not raise
    path.write_text('{"results": {"X": {"state": "ok"}}}', encoding="utf-8")
    assert load_snapshot(path) == {"X": "ok"}


@pytest.mark.asyncio
async def test_check_links_probes_every_url():
    cfg = AppConfig(
        companies=TieredCompanies(tiers={"hard": [
            CompanyConfig(name="Alive", ats="greenhouse", url="https://example.com/alive"),
            CompanyConfig(name="Down", ats="greenhouse", url="https://example.com/down"),
            CompanyConfig(name="Missing", ats="greenhouse", url="https://example.com/missing"),
        ]}),
    )
    async with respx.mock:
        respx.get("https://example.com/alive").respond(200)
        respx.get("https://example.com/down").mock(side_effect=httpx.ConnectError("dns"))
        respx.get("https://example.com/missing").respond(404)
        report = await check_links(cfg, timeout=5)

    assert report["total"] == 3
    states = {name: rec["state"] for name, rec in report["results"].items()}
    assert states == {"Alive": "ok", "Down": "dead", "Missing": "dead"}
    assert report["counts"] == {"ok": 1, "blocked": 0, "dead": 2}
    # browser confirmation must not launch for API-only companies
    assert "browser_error" not in report["results"]["Down"]


@pytest.mark.asyncio
async def test_probe_survives_bad_url():
    """A malformed URL must degrade to a dead record, not kill the check."""
    record = {"name": "Bad", "tier": "hard", "ats": "greenhouse", "url": "not-a-url"}
    async with httpx.AsyncClient(timeout=5) as client:
        rec = await probe_company(client, record)
    assert rec["state"] == "dead"
    assert rec["error"]
