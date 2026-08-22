from tracker.database import JobRepository, compute_hash
from tracker.dedup import should_skip_dedup
from tracker.models import RawJob


def test_compute_hash_is_consistent():
    h1 = compute_hash("Stripe", "SWE Intern", "https://stripe.com/jobs/1")
    h2 = compute_hash("Stripe", "SWE Intern", "https://stripe.com/jobs/1")
    assert h1 == h2


def test_compute_hash_differs_on_company():
    h1 = compute_hash("Stripe", "SWE Intern", "https://stripe.com/jobs/1")
    h2 = compute_hash("Razorpay", "SWE Intern", "https://stripe.com/jobs/1")
    assert h1 != h2


def test_compute_hash_differs_on_url():
    h1 = compute_hash("Stripe", "SWE Intern", "https://stripe.com/jobs/1")
    h2 = compute_hash("Stripe", "SWE Intern", "https://stripe.com/jobs/2")
    assert h1 != h2


def test_repo_upsert_and_dedup(tmp_path):
    repo = JobRepository(str(tmp_path / "test.db"))
    job = RawJob(
        company="Stripe",
        title="SWE Intern",
        location="Bangalore",
        url="https://stripe.com/jobs/1",
        description="Python intern",
        employment_type="Intern",
        date_posted="2026-06-15T10:00:00Z",
        source_ats="greenhouse",
    )
    inserted = repo.upsert(job)
    assert inserted is not None
    assert inserted.id is not None
    assert repo.is_seen(job) is True
    assert repo.is_notified(job) is False

    dup = repo.upsert(job)
    assert dup is not None
    assert repo.count() == 1

    repo.close()


def test_mark_notified(tmp_path):
    repo = JobRepository(str(tmp_path / "test.db"))
    job = RawJob(
        company="Stripe",
        title="SWE Intern",
        location="Bangalore",
        url="https://stripe.com/jobs/2",
        description=None,
        employment_type=None,
        date_posted=None,
        source_ats="greenhouse",
    )
    inserted = repo.upsert(job)
    assert repo.is_notified(job) is False
    repo.mark_notified(inserted.id)
    assert repo.is_notified(job) is True
    repo.close()


def test_get_unnotified(tmp_path):
    repo = JobRepository(str(tmp_path / "test.db"))
    j1 = RawJob("A", "SWE Intern", None, "https://a.com/1", None, None, None, "greenhouse")
    j2 = RawJob("B", "DS Intern", None, "https://b.com/1", None, None, None, "lever")
    r1 = repo.upsert(j1)
    repo.upsert(j2)
    repo.mark_notified(r1.id)
    unnotified = repo.get_unnotified()
    assert len(unnotified) == 1
    assert unnotified[0].company == "B"
    repo.close()


def _backdate_last_seen(repo: JobRepository, job_id: int, days: int = 200) -> None:
    repo._conn.execute(
        "UPDATE jobs SET date_last_seen = datetime('now', ?) WHERE id = ?",
        (f"-{days} days", job_id),
    )
    repo._conn.commit()


def test_skip_dedup_refreshes_last_seen(tmp_path):
    repo = JobRepository(str(tmp_path / "test.db"))
    job = RawJob("A", "SWE Intern", None, "https://a.com/9", None, None, None, "greenhouse")
    row = repo.upsert(job)
    repo.mark_notified(row.id)
    _backdate_last_seen(repo, row.id)
    old_seen = repo.get_by_id(row.id).date_last_seen

    assert should_skip_dedup(job, repo, True) is True
    assert repo.get_by_id(row.id).date_last_seen > old_seen
    repo.close()


def test_prune_deletes_stale_notified_only(tmp_path):
    repo = JobRepository(str(tmp_path / "test.db"))
    stale = RawJob("A", "Old Intern", None, "https://a.com/old", None, None, None, "greenhouse")
    fresh = RawJob("B", "New Intern", None, "https://b.com/new", None, None, None, "greenhouse")
    unseen = RawJob("C", "Unnotified Intern", None, "https://c.com/x", None, None, None, "greenhouse")
    stale_row = repo.upsert(stale)
    repo.mark_notified(stale_row.id)
    _backdate_last_seen(repo, stale_row.id)
    fresh_row = repo.upsert(fresh)
    repo.mark_notified(fresh_row.id)
    unseen_row = repo.upsert(unseen)
    _backdate_last_seen(repo, unseen_row.id)  # unnotified must survive regardless of age

    deleted = repo.prune(90)
    assert deleted == 1
    assert repo.get_by_id(stale_row.id) is None
    assert repo.get_by_id(fresh_row.id) is not None
    assert repo.get_by_id(unseen_row.id) is not None
    repo.close()
