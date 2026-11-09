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


def test_projects_are_private_and_count_their_jobs(tmp_path):
    repository = Repository(f"sqlite:///{(tmp_path / 'projects.db').as_posix()}", 100)
    project = repository.create_project("user-1", "project-1", "Podcast Launch")
    duplicate = repository.create_project("user-1", "project-2", "podcast launch")
    job = sample_job()
    job.update(project_id=project["id"], project_name=project["name"], title="Episode one")
    repository.create_job_and_reserve("user-1", job, 40)

    projects = repository.list_projects("user-1")
    assert duplicate["id"] == project["id"]
    assert projects[0]["name"] == "Podcast Launch"
    assert projects[0]["job_count"] == 1
    assert repository.get_project("project-1", "user-2") is None
