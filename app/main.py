from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .auth import get_current_user
from .config import settings
from .dispatcher import create_generation_engine
from .engine import MODEL_OPTIONS, SUPPORTED_LANGUAGES, GenerationOptions, normalize_reference
from .repository import InsufficientCredits, Repository
from .storage import AudioStorage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("voiceforge")

static_dir = Path(__file__).parent / "static"
engine = create_generation_engine()
repository = Repository(settings.resolved_database_url, settings.starter_credits)
audio_storage = AudioStorage()
executor = ThreadPoolExecutor(max_workers=max(1, settings.workers))


@asynccontextmanager
async def lifespan(_: FastAPI):
    def reconcile_interrupted_jobs() -> None:
        try:
            for interrupted in repository.fail_incomplete_jobs():
                repository.refund(
                    interrupted["user_id"],
                    interrupted["id"],
                    int(interrupted.get("credits", 0)),
                )
        except Exception:
            logger.exception("Startup job reconciliation failed")

    # Database availability must not block the public site or health endpoint.
    executor.submit(reconcile_interrupted_jobs)
    yield


app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def public_job(job: dict) -> dict:
    private = {"reference_path", "output_path", "audio_locator"}
    return {key: value for key, value in job.items() if key not in private}


def update_job(job_id: str, **changes) -> dict:
    return repository.update_job(job_id, **changes)


def run_generation(
    job_id: str,
    user_id: str,
    text: str,
    reference_path: Path,
    options: GenerationOptions,
) -> None:
    output_path = settings.jobs_dir / job_id / "voiceover.wav"
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        update_job(job_id, status="processing", stage="Starting secure GPU worker", progress=8)

        def progress(done: int, total: int) -> None:
            percent = 15 + int((done / total) * 75)
            update_job(
                job_id,
                status="processing",
                stage=f"Generating section {done} of {total}",
                progress=percent,
            )

        engine.generate(text, reference_path, output_path, options, progress)
        locator = audio_storage.store(output_path, f"voiceovers/{user_id}/{job_id}.wav")
        update_job(
            job_id,
            status="completed",
            stage="Ready",
            progress=100,
            completed_at=now_iso(),
            audio_locator=locator,
            audio_url=f"/api/jobs/{job_id}/audio",
            download_name=f"ai-voice-{job_id[:8]}.wav",
        )
    except Exception as exc:
        logger.exception("Generation failed for job %s", job_id)
        job = repository.get_job(job_id)
        credits = int(job.get("credits", 0)) if job else 0
        repository.refund(user_id, job_id, credits)
        update_job(
            job_id,
            status="failed",
            stage="Generation failed — credits refunded",
            error=str(exc),
            completed_at=now_iso(),
        )
    finally:
        reference_path.unlink(missing_ok=True)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "environment": settings.environment,
        "engine": settings.engine,
        "worker_mode": settings.worker_mode,
        "device": engine.device,
        "loaded_model": engine.loaded_model,
    }


@app.get("/api/config")
def config() -> dict:
    return {
        "brand": settings.app_name,
        "models": MODEL_OPTIONS,
        "languages": SUPPORTED_LANGUAGES,
        "limits": {
            "max_text_chars": settings.max_text_chars,
            "max_upload_mb": settings.max_upload_mb,
        },
        "credits": {"per_character": 1, "starter": settings.starter_credits},
        "auth": {
            "mode": settings.auth_mode,
            "supabase_url": settings.supabase_url if settings.auth_mode == "supabase" else None,
            "supabase_anon_key": (
                settings.supabase_anon_key if settings.auth_mode == "supabase" else None
            ),
        },
    }


@app.get("/api/account")
def account(user_id: str = Depends(get_current_user)) -> dict:
    return {"id": user_id, "credits": repository.balance(user_id)}


@app.get("/api/jobs")
def list_jobs(user_id: str = Depends(get_current_user)) -> list[dict]:
    return [public_job(job) for job in repository.list_jobs(user_id)]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, user_id: str = Depends(get_current_user)) -> dict:
    job = repository.get_job(job_id, user_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return public_job(job)


@app.get("/api/jobs/{job_id}/audio")
def get_audio(
    job_id: str,
    download: bool = False,
    user_id: str = Depends(get_current_user),
):
    job = repository.get_job(job_id, user_id)
    if not job or job.get("status") != "completed":
        raise HTTPException(status_code=404, detail="Audio is not ready")
    locator = job.get("audio_locator") or job.get("output_path")
    if not locator:
        raise HTTPException(status_code=404, detail="Audio file is unavailable")
    remote_url = audio_storage.url(locator, job["download_name"] if download else None)
    if remote_url:
        return RedirectResponse(remote_url)
    path = Path(locator)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio file is unavailable")
    filename = job["download_name"] if download else None
    return FileResponse(path, media_type="audio/wav", filename=filename)


@app.post("/api/generate", status_code=202)
async def generate(
    reference: Annotated[UploadFile, File(...)],
    text: Annotated[str, Form(...)],
    model: Annotated[str, Form()] = "multilingual-v3",
    language: Annotated[str, Form()] = "en",
    exaggeration: Annotated[float, Form()] = 0.5,
    cfg_weight: Annotated[float, Form()] = 0.5,
    temperature: Annotated[float, Form()] = 0.8,
    consent: Annotated[bool, Form()] = False,
    user_id: str = Depends(get_current_user),
) -> dict:
    text = text.strip()
    if not consent:
        raise HTTPException(status_code=400, detail="Voice-owner consent is required")
    if not text:
        raise HTTPException(status_code=400, detail="Add a script to generate")
    if len(text) > settings.max_text_chars:
        raise HTTPException(
            status_code=400,
            detail=f"Script exceeds the {settings.max_text_chars:,}-character limit",
        )
    if model not in MODEL_OPTIONS:
        raise HTTPException(status_code=400, detail="Unsupported model")
    if language not in MODEL_OPTIONS[model]["languages"]:
        raise HTTPException(status_code=400, detail="Language is not supported by that model")
    if not 0 <= exaggeration <= 1 or not 0 <= cfg_weight <= 1 or not 0.1 <= temperature <= 2:
        raise HTTPException(status_code=400, detail="Generation controls are out of range")

    job_id = uuid.uuid4().hex
    upload_suffix = Path(reference.filename or "reference.wav").suffix.lower() or ".audio"
    raw_path = settings.uploads_dir / f"{job_id}-raw{upload_suffix}"
    normalized_path = settings.uploads_dir / f"{job_id}.wav"
    max_bytes = settings.max_upload_mb * 1024 * 1024
    size = 0
    with raw_path.open("wb") as target:
        while chunk := await reference.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                target.close()
                raw_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Reference audio is too large")
            target.write(chunk)

    try:
        normalize_reference(raw_path, normalized_path)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        raw_path.unlink(missing_ok=True)

    credits = len(text)
    job = {
        "id": job_id,
        "status": "queued",
        "stage": "Queued",
        "progress": 2,
        "created_at": now_iso(),
        "completed_at": None,
        "model": model,
        "language": language,
        "characters": len(text),
        "credits": credits,
        "text_preview": text[:120] + ("…" if len(text) > 120 else ""),
        "reference_path": str(normalized_path),
        "output_path": str(settings.jobs_dir / job_id / "voiceover.wav"),
        "audio_locator": None,
        "audio_url": None,
        "download_name": None,
        "error": None,
        "consent_attested": True,
    }
    try:
        repository.create_job_and_reserve(user_id, job, credits)
    except InsufficientCredits as exc:
        normalized_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=402,
            detail={
                "message": "Not enough credits",
                "required": exc.required,
                "balance": exc.balance,
            },
        ) from exc

    options = GenerationOptions(model, language, exaggeration, cfg_weight, temperature)
    executor.submit(run_generation, job_id, user_id, text, normalized_path, options)
    return public_job(job)


app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
