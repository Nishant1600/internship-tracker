from tracker.database import JobRepository, compute_hash
from tracker.models import RawJob


def should_skip_dedup(
    job: RawJob, repo: JobRepository, dedup_notifications: bool
) -> bool:
    desc_hash = compute_hash(job.company, job.title, job.url)
    existing = repo.find_by_hash(desc_hash)
    if existing is None:
        return False
    if dedup_notifications and existing.notified_at is not None:
        repo.touch(existing.id)  # keep date_last_seen accurate so pruning works
        return True
    return False
