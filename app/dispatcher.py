from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Callable

import httpx

from .config import settings
from .engine import GenerationOptions, create_engine


class RunPodEngine:
    device = "remote-gpu"
    loaded_model = None

    def __init__(self) -> None:
        if not settings.runpod_endpoint_id or not settings.runpod_api_key:
            raise RuntimeError("RunPod endpoint ID and API key are required in runpod mode")
        self.base_url = f"https://api.runpod.ai/v2/{settings.runpod_endpoint_id}"

    def _run(self, payload: dict) -> dict:
        headers = {"Authorization": f"Bearer {settings.runpod_api_key}"}
        with httpx.Client(timeout=60) as client:
            response = client.post(
                f"{self.base_url}/run", headers=headers, json={"input": payload}
            )
            response.raise_for_status()
            run_id = response.json()["id"]
            deadline = time.monotonic() + settings.runpod_timeout_seconds
            while time.monotonic() < deadline:
                status_response = client.get(f"{self.base_url}/status/{run_id}", headers=headers)
                status_response.raise_for_status()
                result = status_response.json()
                status = result.get("status")
                if status == "COMPLETED":
                    output = result.get("output") or {}
                    if output.get("error"):
                        raise RuntimeError(output["error"])
                    return output
                if status in {"FAILED", "CANCELLED", "TIMED_OUT"}:
                    raise RuntimeError(result.get("error") or f"GPU worker ended with {status}")
                time.sleep(2)
        raise TimeoutError("GPU worker exceeded the configured timeout")

    def generate(
        self,
        text: str,
        reference_path: Path | None,
        output_path: Path,
        options: GenerationOptions,
        progress: Callable[[int, int], None] | None = None,
    ) -> None:
        payload = {
            "task": "generate",
            "text": text,
            "model": options.model,
            "language": options.language,
            "voice": options.voice,
            "exaggeration": options.exaggeration,
            "cfg_weight": options.cfg_weight,
            "temperature": options.temperature,
            "speed": options.speed,
        }
        if reference_path is not None:
            payload["reference_audio"] = base64.b64encode(
                reference_path.read_bytes()
            ).decode("ascii")
        output = self._run(payload)
        output_path.write_bytes(base64.b64decode(output["audio_base64"]))
        if progress:
            progress(1, 1)

    def translate(
        self,
        text: str,
        source_language: str,
        target_languages: list[str],
    ) -> dict[str, str]:
        output = self._run(
            {
                "task": "translate",
                "text": text,
                "source_language": source_language,
                "target_languages": target_languages,
            }
        )
        translations = output.get("translations")
        if not isinstance(translations, dict):
            raise RuntimeError("GPU worker returned an invalid translation")
        return {str(language): str(value) for language, value in translations.items()}


def create_generation_engine():
    if settings.worker_mode == "runpod":
        return RunPodEngine()
    if settings.worker_mode != "local":
        raise RuntimeError(f"Unsupported worker mode: {settings.worker_mode}")
    return create_engine(settings.device, settings.engine)
