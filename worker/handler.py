from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path

import runpod
import torch

from app.config import settings
from app.engine import GenerationOptions, create_engine

engine = create_engine(settings.device, settings.engine)


def log_runtime() -> None:
    runtime = {
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "cuda_arches": torch.cuda.get_arch_list(),
    }
    if runtime["cuda_available"]:
        runtime["gpu"] = torch.cuda.get_device_name(0)
        runtime["compute_capability"] = torch.cuda.get_device_capability(0)
    print(f"VOICEFORGE_RUNTIME {json.dumps(runtime, default=str)}", flush=True)


def handler(event: dict) -> dict:
    payload = event.get("input") or {}
    if payload.get("healthcheck") is True:
        try:
            if not torch.cuda.is_available():
                return {"error": "CUDA is not available"}
            # Execute an actual CUDA kernel, not just a device capability check.
            result = (torch.ones(1, device="cuda") * 2).item()
            return {
                "ok": result == 2,
                "torch": torch.__version__,
                "cuda": torch.version.cuda,
                "gpu": torch.cuda.get_device_name(0),
                "compute_capability": torch.cuda.get_device_capability(0),
            }
        except Exception as exc:
            return {"error": str(exc)}

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
    log_runtime()
    runpod.serverless.start({"handler": handler})
