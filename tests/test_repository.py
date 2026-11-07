from datetime import UTC, datetime

from app.repository import InsufficientCredits, Repository


def sample_job(job_id: str = "job-1") -> dict:
    return {
        "id": job_id,
        "status": "queued",
        "created_at": datetime.now(UTC).isoformat(),
        "credits": 40,
    }


def test_credit_reservation_and_idempotent_refund(tmp_path):
    repository = Repository(f"sqlite:///{(tmp_path / 'credits.db').as_posix()}", 100)
    repository.create_job_and_reserve("user-1", sample_job(), 40)
    assert repository.balance("user-1") == 60

    repository.refund("user-1", "job-1", 40)
    repository.refund("user-1", "job-1", 40)
    assert repository.balance("user-1") == 100


def test_insufficient_credits_do_not_create_job(tmp_path):
    repository = Repository(f"sqlite:///{(tmp_path / 'credits.db').as_posix()}", 25)
    try:
        repository.create_job_and_reserve("user-1", sample_job(), 40)
    except InsufficientCredits as exc:
        assert exc.balance == 25
        assert exc.required == 40
    else:
        raise AssertionError("Expected the reservation to be rejected")

    assert repository.balance("user-1") == 25
    assert repository.get_job("job-1", "user-1") is None
