from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from langdetect import DetectorFactory, LangDetectException, detect

from .auth import get_current_user
from .billing import InvalidWebhookSignature, first_price_id, parse_event, verify_paddle_signature
from .config import settings
from .dispatcher import create_generation_engine
from .engine import (
    MODEL_OPTIONS,
    SUPPORTED_LANGUAGES,
    TRANSLATION_SOURCE_LANGUAGES,
    VOICE_OPTIONS,
    GenerationOptions,
    normalize_reference,
)
from .repository import InsufficientCredits, Repository
from .storage import AudioStorage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("voiceforge")

static_dir = Path(__file__).parent / "static"
engine = create_generation_engine()
repository = Repository(settings.resolved_database_url, settings.starter_credits)
audio_storage = AudioStorage()
executor = ThreadPoolExecutor(max_workers=max(1, settings.workers))
DetectorFactory.seed = 0


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


app = FastAPI(title=settings.app_name, version="0.3.0", lifespan=lifespan)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def configured_plan_by_price(price_id: str | None) -> tuple[str | None, dict | None]:
    if not price_id:
        return None, None
    for code, plan in settings.paddle_plans.items():
        if plan["price_id"] == price_id:
            return code, plan
    return None, None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class SavedVoiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    accent: str | None = Field(default=None, max_length=48)
    language: str | None = Field(default=None, max_length=16)
    use_tags: list[str] | None = Field(default=None, max_length=8)
    default_preset: str | None = Field(default=None, max_length=24)


VOICE_CONSENT_VERSION = "2026-11-10"
DELIVERY_PRESETS = {"natural", "warm", "energetic", "dramatic", "calm"}


def resolve_project(user_id: str, project_id: str) -> dict | None:
    project_id = project_id.strip()
    if not project_id:
        return None
    project = repository.get_project(project_id, user_id)
    if not project:
        raise HTTPException(status_code=400, detail="That project is unavailable")
    return project


def task_name(value: str, text: str) -> str:
    cleaned = " ".join(value.split())[:80]
    if cleaned:
        return cleaned
    fallback = " ".join(text.split())[:60]
    return fallback or "Untitled voiceover"


def clean_saved_voice_fields(
    *,
    name: str,
    accent: str,
    language: str,
    use_tags: list[str],
    default_preset: str,
) -> dict:
    cleaned_name = " ".join(name.split())[:80]
    if not cleaned_name:
        raise HTTPException(status_code=400, detail="Give this voice a name")
    cleaned_accent = " ".join(accent.split())[:48] or "Custom"
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Choose a supported primary language")
    if default_preset not in DELIVERY_PRESETS:
        raise HTTPException(status_code=400, detail="Choose a supported delivery preset")
    cleaned_tags: list[str] = []
    for tag in use_tags:
        value = " ".join(tag.split())[:24]
        if value and value.casefold() not in {item.casefold() for item in cleaned_tags}:
            cleaned_tags.append(value)
        if len(cleaned_tags) == 8:
            break
    return {
        "name": cleaned_name,
        "accent": cleaned_accent,
        "language": language,
        "use_tags": cleaned_tags,
        "default_preset": default_preset,
    }


def public_saved_voice(voice: dict) -> dict:
    result = {key: value for key, value in voice.items() if key != "locator"}
    result["preview_url"] = f"/api/voices/{voice['id']}/audio"
    return result


async def normalize_uploaded_reference(
    upload: UploadFile,
    raw_path: Path,
    normalized_path: Path,
) -> None:
    max_bytes = settings.max_upload_mb * 1024 * 1024
    size = 0
    try:
        with raw_path.open("wb") as target:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status_code=413, detail="Reference audio is too large")
                target.write(chunk)
        normalize_reference(raw_path, normalized_path)
    except (ValueError, FileNotFoundError) as exc:
        normalized_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        normalized_path.unlink(missing_ok=True)
        raise
    finally:
        raw_path.unlink(missing_ok=True)


def saved_reference_for_job(saved_voice: dict, job_id: str) -> Path:
    destination = settings.uploads_dir / f"{job_id}.wav"
    try:
        return audio_storage.materialize(saved_voice["locator"], destination)
    except Exception as exc:
        logger.exception("Could not load saved voice %s", saved_voice["id"])
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=502,
            detail="That saved voice is temporarily unavailable",
        ) from exc


def public_job(job: dict) -> dict:
    private = {"reference_path", "output_path", "audio_locator"}
    result = {key: value for key, value in job.items() if key not in private}
    if isinstance(result.get("outputs"), list):
        result["outputs"] = [
            {key: value for key, value in output.items() if key not in private}
            for output in result["outputs"]
        ]
    if isinstance(result.get("takes"), list):
        result["takes"] = [
            {key: value for key, value in take.items() if key not in private}
            for take in result["takes"]
        ]
    return result


def update_job(job_id: str, **changes) -> dict:
    return repository.update_job(job_id, **changes)


def run_generation(
    job_id: str,
    user_id: str,
    text: str,
    reference_path: Path | None,
    options: GenerationOptions,
    variations: int,
) -> None:
    try:
        job_dir = settings.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        update_job(job_id, status="processing", stage="Starting secure GPU worker", progress=8)
        takes = []
        for take_number in range(1, variations + 1):
            output_path = job_dir / f"voiceover-take-{take_number}.wav"

            def progress(done: int, total: int, current_take: int = take_number) -> None:
                completed = (current_take - 1) + (done / total)
                percent = 12 + int((completed / variations) * 80)
                update_job(
                    job_id,
                    status="processing",
                    stage=(
                        f"Generating take {current_take} of {variations}"
                        if variations > 1
                        else f"Generating section {done} of {total}"
                    ),
                    progress=percent,
                )

            engine.generate(text, reference_path, output_path, options, progress)
            locator = audio_storage.store(
                output_path, f"voiceovers/{user_id}/{job_id}/take-{take_number}.wav"
            )
            takes.append(
                {
                    "take": take_number,
                    "label": f"Take {take_number}",
                    "audio_locator": locator,
                    "audio_url": f"/api/jobs/{job_id}/audio?take={take_number}",
                    "download_name": f"ai-voice-{job_id[:8]}-take-{take_number}.wav",
                }
            )
        update_job(
            job_id,
            status="completed",
            stage="Ready",
            progress=100,
            completed_at=now_iso(),
            takes=takes,
            audio_locator=takes[0]["audio_locator"],
            audio_url=takes[0]["audio_url"],
            download_name=takes[0]["download_name"],
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
        if reference_path is not None:
            reference_path.unlink(missing_ok=True)


def run_multilingual_generation(
    job_id: str,
    user_id: str,
    text: str,
    source_language: str,
    target_languages: list[str],
    reference_path: Path | None,
    voice: str,
    exaggeration: float,
    cfg_weight: float,
    temperature: float,
    speed: float,
) -> None:
    try:
        job_dir = settings.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        update_job(job_id, status="processing", stage="Translating your script", progress=8)
        translations = engine.translate(text, source_language, target_languages)
        outputs = []
        total = len(target_languages)
        for index, language in enumerate(target_languages, start=1):
            translated_text = translations.get(language, "").strip()
            if not translated_text:
                raise RuntimeError(f"Translation returned no {language} text")
            update_job(
                job_id,
                status="processing",
                stage=(
                    f"Creating {SUPPORTED_LANGUAGES[language]} voiceover "
                    f"{index} of {total}"
                ),
                progress=15 + int(((index - 1) / total) * 78),
            )
            output_path = job_dir / f"voiceover-{language}.wav"
            options = GenerationOptions(
                "multilingual-v3",
                language,
                exaggeration,
                cfg_weight,
                temperature,
                voice,
                speed,
            )
            engine.generate(translated_text, reference_path, output_path, options)
            locator = audio_storage.store(
                output_path, f"voiceovers/{user_id}/{job_id}/{language}.wav"
            )
            outputs.append(
                {
                    "language": language,
                    "language_label": SUPPORTED_LANGUAGES[language],
                    "characters": len(translated_text),
                    "text_preview": translated_text[:120]
                    + ("…" if len(translated_text) > 120 else ""),
                    "audio_locator": locator,
                    "audio_url": f"/api/jobs/{job_id}/audio?language={language}",
                    "download_name": f"ai-voice-{job_id[:8]}-{language}.wav",
                }
            )
        update_job(
            job_id,
            status="completed",
            stage="All languages ready",
            progress=100,
            completed_at=now_iso(),
            outputs=outputs,
            audio_url=f"/api/jobs/{job_id}/audio?language={target_languages[0]}",
            download_name=outputs[0]["download_name"],
        )
    except Exception as exc:
        logger.exception("Multilingual generation failed for job %s", job_id)
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
        if reference_path is not None:
            reference_path.unlink(missing_ok=True)


def detect_source_language(text: str) -> str:
    try:
        language = detect(text)
    except LangDetectException as exc:
        raise HTTPException(
            status_code=400,
            detail="Could not detect the source language. Choose it manually.",
        ) from exc
    language = {"zh-cn": "zh", "zh-tw": "zh", "iw": "he"}.get(language, language)
    if language not in TRANSLATION_SOURCE_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail="The detected source language is not supported. Choose it manually.",
        )
    return language


def resolve_audio(
    job: dict, language: str | None, take: int | None = None
) -> tuple[str, str]:
    outputs = job.get("outputs") or []
    if outputs:
        selected = next(
            (output for output in outputs if output.get("language") == language),
            outputs[0] if language is None else None,
        )
        if selected is None:
            raise HTTPException(status_code=404, detail="That language output is unavailable")
        locator = selected.get("audio_locator") or selected.get("output_path")
        filename = selected.get("download_name") or f"ai-voice-{job['id'][:8]}.wav"
    elif job.get("takes"):
        takes = job["takes"]
        selected = next(
            (candidate for candidate in takes if candidate.get("take") == take),
            takes[0] if take is None else None,
        )
        if selected is None:
            raise HTTPException(status_code=404, detail="That take is unavailable")
        locator = selected.get("audio_locator") or selected.get("output_path")
        filename = selected.get("download_name") or f"ai-voice-{job['id'][:8]}.wav"
    else:
        locator = job.get("audio_locator") or job.get("output_path")
        filename = job.get("download_name") or f"ai-voice-{job['id'][:8]}.wav"
    if not locator:
        raise HTTPException(status_code=404, detail="Audio file is unavailable")
    return locator, filename


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
        "voices": VOICE_OPTIONS,
        "languages": SUPPORTED_LANGUAGES,
        "limits": {
            "max_text_chars": settings.max_text_chars,
            "max_upload_mb": settings.max_upload_mb,
            "max_translation_targets": 5,
        },
        "translation": {
            "source_languages": sorted(TRANSLATION_SOURCE_LANGUAGES),
            "target_languages": list(SUPPORTED_LANGUAGES),
        },
        "credits": {"per_character": 1, "starter": settings.starter_credits},
        "auth": {
            "mode": settings.auth_mode,
            "supabase_url": settings.supabase_url if settings.auth_mode == "supabase" else None,
            "supabase_anon_key": (
                settings.supabase_anon_key if settings.auth_mode == "supabase" else None
            ),
        },
        "billing": {
            "provider": "paddle",
            "enabled": settings.paddle_enabled,
            "environment": settings.paddle_environment,
            "client_token": settings.paddle_client_token if settings.paddle_enabled else None,
            "plans": {
                code: {
                    "name": plan["name"],
                    "interval": plan["interval"],
                    "credits": plan["credits"],
                    "price_id": plan["price_id"],
                }
                for code, plan in settings.paddle_plans.items()
            },
        },
    }


@app.get("/api/account")
def account(user_id: str = Depends(get_current_user)) -> dict:
    subscription = repository.get_subscription(user_id)
    if subscription:
        plan = settings.paddle_plans.get(subscription.get("plan_code") or "")
        subscription["plan_name"] = plan["name"] if plan else subscription.get("plan_code")
        subscription["interval"] = plan["interval"] if plan else None
    return {
        "id": user_id,
        "credits": repository.balance(user_id),
        "subscription": subscription,
    }


@app.post("/api/billing/webhook", include_in_schema=False)
async def paddle_webhook(
    request: Request,
    paddle_signature: str | None = Header(default=None, alias="Paddle-Signature"),
) -> dict:
    if not settings.paddle_webhook_secret:
        raise HTTPException(status_code=503, detail="Billing webhooks are not configured")

    raw_body = await request.body()
    try:
        verify_paddle_signature(raw_body, paddle_signature, settings.paddle_webhook_secret)
        event = parse_event(raw_body)
    except InvalidWebhookSignature as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    data = event.get("data") or {}
    event_type = str(event["event_type"])
    custom_data = data.get("custom_data") or {}
    user_id = str(custom_data.get("user_id")) if custom_data.get("user_id") else None
    price_id = first_price_id(data)
    plan_code, plan = configured_plan_by_price(price_id)
    transaction_id = str(data.get("id")) if event_type == "transaction.completed" else None
    subscription_id = data.get("subscription_id")
    if event_type.startswith("subscription."):
        subscription_id = data.get("id") or subscription_id
    customer_id = data.get("customer_id")

    credits = 0
    if event_type == "transaction.completed":
        if not user_id:
            raise HTTPException(status_code=422, detail="Paid transaction has no account ID")
        if not plan or not plan_code:
            raise HTTPException(status_code=422, detail="Paid transaction uses an unknown price")
        credits = int(plan["credits"])

    scheduled_change = data.get("scheduled_change") or {}
    cancel_at_period_end = scheduled_change.get("action") == "cancel"
    applied = repository.apply_paddle_event(
        event_id=str(event["event_id"]),
        event_type=event_type,
        occurred_at=event.get("occurred_at"),
        user_id=user_id,
        transaction_id=transaction_id,
        subscription_id=str(subscription_id) if subscription_id else None,
        customer_id=str(customer_id) if customer_id else None,
        price_id=price_id,
        plan_code=plan_code,
        status=(
            "active"
            if event_type == "transaction.completed"
            else str(data.get("status") or "active")
        ),
        next_billed_at=data.get("next_billed_at"),
        cancel_at_period_end=cancel_at_period_end,
        credits=credits,
    )
    return {"received": True, "applied": applied}


@app.post("/api/billing/portal")
async def billing_portal(user_id: str = Depends(get_current_user)) -> dict:
    subscription = repository.get_subscription(user_id)
    if not subscription or not subscription.get("customer_id"):
        raise HTTPException(status_code=404, detail="No paid billing account was found")
    if not settings.paddle_api_key:
        raise HTTPException(status_code=503, detail="Billing management is not configured")

    customer_id = subscription["customer_id"]
    payload = {"subscription_ids": [subscription["id"]]}
    headers = {
        "Authorization": f"Bearer {settings.paddle_api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{settings.paddle_api_base_url}/customers/{customer_id}/portal-sessions",
                headers=headers,
                json=payload,
            )
        response.raise_for_status()
        portal_url = response.json()["data"]["urls"]["general"]["overview"]
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        logger.exception("Could not create Paddle customer portal session")
        raise HTTPException(status_code=502, detail="Billing portal is temporarily unavailable") from exc
    return {"url": portal_url}


@app.get("/api/jobs")
def list_jobs(user_id: str = Depends(get_current_user)) -> list[dict]:
    return [public_job(job) for job in repository.list_jobs(user_id)]


@app.get("/api/projects")
def list_projects(user_id: str = Depends(get_current_user)) -> list[dict]:
    return repository.list_projects(user_id)


@app.post("/api/projects", status_code=201)
def create_project(project: ProjectCreate, user_id: str = Depends(get_current_user)) -> dict:
    name = " ".join(project.name.split())
    if not name:
        raise HTTPException(status_code=400, detail="Add a project name")
    return repository.create_project(user_id, uuid.uuid4().hex, name)


@app.get("/api/voices")
def list_saved_voices(user_id: str = Depends(get_current_user)) -> list[dict]:
    return [public_saved_voice(voice) for voice in repository.list_saved_voices(user_id)]


@app.post("/api/voices", status_code=201)
async def create_saved_voice(
    reference: Annotated[UploadFile, File(...)],
    name: Annotated[str, Form(...)],
    accent: Annotated[str, Form()] = "Custom",
    language: Annotated[str, Form()] = "en",
    use_tags: Annotated[str, Form()] = "",
    default_preset: Annotated[str, Form()] = "natural",
    consent: Annotated[bool, Form()] = False,
    user_id: str = Depends(get_current_user),
) -> dict:
    if not consent:
        raise HTTPException(status_code=400, detail="Voice-owner consent is required")
    fields = clean_saved_voice_fields(
        name=name,
        accent=accent,
        language=language,
        use_tags=use_tags.split(","),
        default_preset=default_preset,
    )
    voice_id = uuid.uuid4().hex
    suffix = Path(reference.filename or "reference.wav").suffix.lower() or ".audio"
    raw_path = settings.saved_voices_dir / f"{voice_id}-raw{suffix}"
    normalized_path = settings.saved_voices_dir / f"{voice_id}.wav"
    await normalize_uploaded_reference(reference, raw_path, normalized_path)
    locator: str | None = None
    try:
        locator = audio_storage.store(
            normalized_path,
            f"saved-voices/{user_id}/{voice_id}.wav",
        )
        voice = repository.create_saved_voice(
            user_id,
            voice_id,
            locator=locator,
            consent_version=VOICE_CONSENT_VERSION,
            **fields,
        )
    except Exception:
        if locator:
            try:
                audio_storage.delete(locator)
            except Exception:
                logger.exception("Could not roll back saved voice audio")
        else:
            normalized_path.unlink(missing_ok=True)
        raise
    return public_saved_voice(voice)


@app.patch("/api/voices/{voice_id}")
def update_saved_voice(
    voice_id: str,
    update: SavedVoiceUpdate,
    user_id: str = Depends(get_current_user),
) -> dict:
    existing = repository.get_saved_voice(voice_id, user_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Saved voice not found")
    values = update.model_dump(exclude_unset=True)
    fields = clean_saved_voice_fields(
        name=values.get("name", existing["name"]),
        accent=values.get("accent", existing["accent"]),
        language=values.get("language", existing["language"]),
        use_tags=values.get("use_tags", existing["use_tags"]),
        default_preset=values.get("default_preset", existing["default_preset"]),
    )
    voice = repository.update_saved_voice(voice_id, user_id, **fields)
    assert voice is not None
    return public_saved_voice(voice)


@app.put("/api/voices/{voice_id}/sample")
async def replace_saved_voice_sample(
    voice_id: str,
    reference: Annotated[UploadFile, File(...)],
    consent: Annotated[bool, Form()] = False,
    user_id: str = Depends(get_current_user),
) -> dict:
    voice = repository.get_saved_voice(voice_id, user_id)
    if not voice:
        raise HTTPException(status_code=404, detail="Saved voice not found")
    if not consent:
        raise HTTPException(status_code=400, detail="Voice-owner consent is required")
    replacement_id = uuid.uuid4().hex
    suffix = Path(reference.filename or "reference.wav").suffix.lower() or ".audio"
    raw_path = settings.saved_voices_dir / f"{replacement_id}-raw{suffix}"
    normalized_path = settings.saved_voices_dir / f"{replacement_id}.wav"
    await normalize_uploaded_reference(reference, raw_path, normalized_path)
    locator = audio_storage.store(
        normalized_path,
        f"saved-voices/{user_id}/{voice_id}.wav",
    )
    updated = repository.update_saved_voice(
        voice_id,
        user_id,
        locator=locator,
        refresh_consent=True,
        consent_version=VOICE_CONSENT_VERSION,
    )
    if locator != voice["locator"]:
        try:
            audio_storage.delete(voice["locator"])
        except Exception:
            logger.exception("Could not remove replaced saved voice audio")
    assert updated is not None
    return public_saved_voice(updated)


@app.delete("/api/voices/{voice_id}")
def delete_saved_voice(voice_id: str, user_id: str = Depends(get_current_user)) -> dict:
    voice = repository.get_saved_voice(voice_id, user_id)
    if not voice:
        raise HTTPException(status_code=404, detail="Saved voice not found")
    try:
        audio_storage.delete(voice["locator"])
    except Exception as exc:
        logger.exception("Could not remove saved voice audio")
        raise HTTPException(status_code=502, detail="Could not securely delete that voice") from exc
    repository.delete_saved_voice(voice_id, user_id)
    return {"deleted": True}


@app.get("/api/voices/{voice_id}/audio")
def get_saved_voice_audio(voice_id: str, user_id: str = Depends(get_current_user)):
    voice = repository.get_saved_voice(voice_id, user_id)
    if not voice:
        raise HTTPException(status_code=404, detail="Saved voice not found")
    remote_url = audio_storage.url(voice["locator"])
    if remote_url:
        return RedirectResponse(remote_url)
    path = Path(voice["locator"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Saved voice audio is unavailable")
    return FileResponse(path, media_type="audio/wav")


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
    language: str | None = None,
    take: int | None = None,
    user_id: str = Depends(get_current_user),
):
    job = repository.get_job(job_id, user_id)
    if not job or job.get("status") != "completed":
        raise HTTPException(status_code=404, detail="Audio is not ready")
    locator, filename = resolve_audio(job, language, take)
    remote_url = audio_storage.url(locator, filename if download else None)
    if remote_url:
        return RedirectResponse(remote_url)
    path = Path(locator)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio file is unavailable")
    return FileResponse(path, media_type="audio/wav", filename=filename if download else None)


@app.get("/api/jobs/{job_id}/audio-url")
def get_audio_url(
    job_id: str,
    download: bool = False,
    language: str | None = None,
    take: int | None = None,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Return a short-lived direct URL without proxying the WAV through Render."""
    job = repository.get_job(job_id, user_id)
    if not job or job.get("status") != "completed":
        raise HTTPException(status_code=404, detail="Audio is not ready")
    locator, filename = resolve_audio(job, language, take)
    remote_url = audio_storage.url(locator, filename if download else None)
    if remote_url:
        return {"url": remote_url, "download_name": filename, "expires_in": 900}
    path = Path(locator)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio file is unavailable")
    parameters = []
    if language:
        parameters.append(f"language={language}")
    if take:
        parameters.append(f"take={take}")
    if download:
        parameters.append("download=true")
    suffix = f"?{'&'.join(parameters)}" if parameters else ""
    return {
        "url": f"/api/jobs/{job_id}/audio{suffix}",
        "download_name": filename,
        "expires_in": None,
    }


@app.post("/api/generate", status_code=202)
async def generate(
    text: Annotated[str, Form(...)],
    reference: Annotated[UploadFile | None, File()] = None,
    model: Annotated[str, Form()] = "multilingual-v3",
    language: Annotated[str, Form()] = "en",
    voice: Annotated[str, Form()] = "clone",
    saved_voice_id: Annotated[str, Form()] = "",
    exaggeration: Annotated[float, Form()] = 0.5,
    cfg_weight: Annotated[float, Form()] = 0.5,
    temperature: Annotated[float, Form()] = 0.8,
    speed: Annotated[float, Form()] = 1.0,
    variations: Annotated[int, Form()] = 1,
    consent: Annotated[bool, Form()] = False,
    project_id: Annotated[str, Form()] = "",
    title: Annotated[str, Form()] = "",
    user_id: str = Depends(get_current_user),
) -> dict:
    text = text.strip()
    project = resolve_project(user_id, project_id)
    saved_voice_id = saved_voice_id.strip()
    saved_voice = None
    if saved_voice_id:
        saved_voice = repository.get_saved_voice(saved_voice_id, user_id)
        if not saved_voice:
            raise HTTPException(status_code=400, detail="That saved voice is unavailable")
        voice = "clone"
    if voice not in VOICE_OPTIONS:
        raise HTTPException(status_code=400, detail="Unsupported voice")
    voice_option = VOICE_OPTIONS[voice]
    is_clone = voice_option["engine"] == "chatterbox"
    if voice_option["engine"] == "chatterbox-default" and model != "multilingual-v3":
        raise HTTPException(status_code=400, detail="Global Narrator requires Multilingual V3")
    if is_clone and not saved_voice and not consent:
        raise HTTPException(status_code=400, detail="Voice-owner consent is required")
    if is_clone and not saved_voice and reference is None:
        raise HTTPException(status_code=400, detail="Add or record a reference voice first")
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
    if language not in voice_option["languages"]:
        raise HTTPException(status_code=400, detail="Language is not supported by that voice")
    if not 0 <= exaggeration <= 1 or not 0 <= cfg_weight <= 1 or not 0.1 <= temperature <= 2:
        raise HTTPException(status_code=400, detail="Generation controls are out of range")
    if not 0.75 <= speed <= 1.25:
        raise HTTPException(status_code=400, detail="Speaking speed must be between 0.75x and 1.25x")
    if variations not in {1, 2}:
        raise HTTPException(status_code=400, detail="Choose one or two takes")

    job_id = uuid.uuid4().hex
    normalized_path: Path | None = None
    if saved_voice:
        normalized_path = saved_reference_for_job(saved_voice, job_id)
    elif is_clone and reference is not None:
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

    credits = len(text) * variations
    job = {
        "id": job_id,
        "status": "queued",
        "stage": "Queued",
        "progress": 2,
        "created_at": now_iso(),
        "completed_at": None,
        "model": model,
        "voice": voice,
        "voice_label": saved_voice["name"] if saved_voice else voice_option["label"],
        "voice_source": "saved" if saved_voice else ("clone" if is_clone else "ready-made"),
        "saved_voice_id": saved_voice_id or None,
        "language": language,
        "characters": len(text),
        "credits": credits,
        "title": task_name(title, text),
        "project_id": project["id"] if project else None,
        "project_name": project["name"] if project else "Unfiled",
        "variations": variations,
        "speed": speed,
        "text_preview": text[:120] + ("…" if len(text) > 120 else ""),
        "reference_path": str(normalized_path) if normalized_path else None,
        "output_path": str(settings.jobs_dir / job_id / "voiceover.wav"),
        "audio_locator": None,
        "audio_url": None,
        "download_name": None,
        "error": None,
        "consent_attested": bool(saved_voice or consent) if is_clone else False,
    }
    try:
        repository.create_job_and_reserve(user_id, job, credits)
    except InsufficientCredits as exc:
        if normalized_path is not None:
            normalized_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=402,
            detail={
                "message": "Not enough credits",
                "required": exc.required,
                "balance": exc.balance,
            },
        ) from exc

    if saved_voice:
        repository.mark_saved_voice_used(saved_voice_id, user_id)

    options = GenerationOptions(
        model, language, exaggeration, cfg_weight, temperature, voice, speed
    )
    executor.submit(
        run_generation, job_id, user_id, text, normalized_path, options, variations
    )
    return public_job(job)


@app.post("/api/generate-multilingual", status_code=202)
async def generate_multilingual(
    text: Annotated[str, Form(...)],
    target_languages: Annotated[str, Form(...)],
    reference: Annotated[UploadFile | None, File()] = None,
    source_language: Annotated[str, Form()] = "auto",
    voice: Annotated[str, Form()] = "global",
    saved_voice_id: Annotated[str, Form()] = "",
    exaggeration: Annotated[float, Form()] = 0.5,
    cfg_weight: Annotated[float, Form()] = 0.5,
    temperature: Annotated[float, Form()] = 0.8,
    speed: Annotated[float, Form()] = 1.0,
    consent: Annotated[bool, Form()] = False,
    project_id: Annotated[str, Form()] = "",
    title: Annotated[str, Form()] = "",
    user_id: str = Depends(get_current_user),
) -> dict:
    text = text.strip()
    project = resolve_project(user_id, project_id)
    saved_voice_id = saved_voice_id.strip()
    saved_voice = None
    if saved_voice_id:
        saved_voice = repository.get_saved_voice(saved_voice_id, user_id)
        if not saved_voice:
            raise HTTPException(status_code=400, detail="That saved voice is unavailable")
        voice = "clone"
    targets = list(dict.fromkeys(code.strip() for code in target_languages.split(",") if code.strip()))
    if not text:
        raise HTTPException(status_code=400, detail="Add a script to translate")
    if len(text) > settings.max_text_chars:
        raise HTTPException(
            status_code=400,
            detail=f"Script exceeds the {settings.max_text_chars:,}-character limit",
        )
    if not targets:
        raise HTTPException(status_code=400, detail="Choose at least one output language")
    if len(targets) > 5:
        raise HTTPException(status_code=400, detail="Choose up to 5 output languages at once")
    if any(language not in SUPPORTED_LANGUAGES for language in targets):
        raise HTTPException(status_code=400, detail="One or more output languages are unsupported")
    if source_language == "auto":
        source_language = detect_source_language(text)
    elif source_language not in TRANSLATION_SOURCE_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported source language")
    if voice not in VOICE_OPTIONS:
        raise HTTPException(status_code=400, detail="Unsupported voice")
    voice_option = VOICE_OPTIONS[voice]
    is_clone = voice_option["engine"] == "chatterbox"
    if voice_option["engine"] not in {"chatterbox", "chatterbox-default"}:
        raise HTTPException(
            status_code=400,
            detail="Choose Global Narrator or an authorized cloned voice for translation",
        )
    if any(language not in voice_option["languages"] for language in targets):
        raise HTTPException(status_code=400, detail="That voice does not support every output language")
    if is_clone and not saved_voice and not consent:
        raise HTTPException(status_code=400, detail="Voice-owner consent is required")
    if is_clone and not saved_voice and reference is None:
        raise HTTPException(status_code=400, detail="Add or record a reference voice first")
    if not 0 <= exaggeration <= 1 or not 0 <= cfg_weight <= 1 or not 0.1 <= temperature <= 2:
        raise HTTPException(status_code=400, detail="Generation controls are out of range")
    if not 0.75 <= speed <= 1.25:
        raise HTTPException(status_code=400, detail="Speaking speed must be between 0.75x and 1.25x")

    job_id = uuid.uuid4().hex
    normalized_path: Path | None = None
    if saved_voice:
        normalized_path = saved_reference_for_job(saved_voice, job_id)
    elif is_clone and reference is not None:
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

    credits = len(text) * len(targets)
    job = {
        "id": job_id,
        "kind": "multilingual",
        "status": "queued",
        "stage": "Queued",
        "progress": 2,
        "created_at": now_iso(),
        "completed_at": None,
        "model": "multilingual-v3",
        "voice": voice,
        "voice_label": saved_voice["name"] if saved_voice else voice_option["label"],
        "voice_source": "saved" if saved_voice else ("clone" if is_clone else "ready-made"),
        "saved_voice_id": saved_voice_id or None,
        "source_language": source_language,
        "target_languages": targets,
        "language": "multiple",
        "characters": len(text),
        "credits": credits,
        "title": task_name(title, text),
        "project_id": project["id"] if project else None,
        "project_name": project["name"] if project else "Unfiled",
        "text_preview": text[:120] + ("…" if len(text) > 120 else ""),
        "reference_path": str(normalized_path) if normalized_path else None,
        "outputs": [],
        "audio_url": None,
        "download_name": None,
        "error": None,
        "consent_attested": bool(saved_voice or consent) if is_clone else False,
    }
    try:
        repository.create_job_and_reserve(user_id, job, credits)
    except InsufficientCredits as exc:
        if normalized_path is not None:
            normalized_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=402,
            detail={
                "message": "Not enough credits",
                "required": exc.required,
                "balance": exc.balance,
            },
        ) from exc

    if saved_voice:
        repository.mark_saved_voice_used(saved_voice_id, user_id)

    executor.submit(
        run_multilingual_generation,
        job_id,
        user_id,
        text,
        source_language,
        targets,
        normalized_path,
        voice,
        exaggeration,
        cfg_weight,
        temperature,
        speed,
    )
    return public_job(job)


@app.get("/pricing", include_in_schema=False)
@app.get("/studio", include_in_schema=False)
@app.get("/changelog", include_in_schema=False)
@app.get("/faq", include_in_schema=False)
@app.get("/about", include_in_schema=False)
@app.get("/privacy", include_in_schema=False)
@app.get("/terms", include_in_schema=False)
def public_page(request: Request) -> HTMLResponse:
    """Declare each public page's canonical in the original HTML response."""
    # These explicit routes use the public origin, never a proxy/preview Host or query string.
    canonical_url = f"https://aivoicegeneratorhq.com{request.url.path}"
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    html = html.replace(
        '<link rel="canonical" href="https://aivoicegeneratorhq.com/" />',
        f'<link rel="canonical" href="{canonical_url}" />',
        1,
    ).replace(
        '<meta property="og:url" content="https://aivoicegeneratorhq.com/" />',
        f'<meta property="og:url" content="{canonical_url}" />',
        1,
    )
    return HTMLResponse(html)


app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
