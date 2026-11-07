from __future__ import annotations

import base64
import tempfile
from pathlib import Path

import runpod

from app.config import settings
from app.engine import GenerationOptions, create_engine

engine = create_engine(settings.device, settings.engine)


def handler(event: dict) -> dict:
    payload = event.get("input") or {}
    required = {"text", "reference_audio", "model", "language"}
    missing = sorted(required - payload.keys())
    if missing:
        return {"error": f"Missing input: {', '.join(missing)}"}

    try:
        reference_bytes = base64.b64decode(payload["reference_audio"], validate=True)
        options = GenerationOptions(
            model=payload["model"],
            language=payload["language"],
            exaggeration=float(payload.get("exaggeration", 0.5)),
            cfg_weight=float(payload.get("cfg_weight", 0.5)),
            temperature=float(payload.get("temperature", 0.8)),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            reference_path = Path(temp_dir) / "reference.wav"
            output_path = Path(temp_dir) / "voiceover.wav"
            reference_path.write_bytes(reference_bytes)
            engine.generate(payload["text"], reference_path, output_path, options)
            return {"audio_base64": base64.b64encode(output_path.read_bytes()).decode("ascii")}
    except Exception as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
