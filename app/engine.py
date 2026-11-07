from __future__ import annotations

import math
import os
import re
import shutil
import struct
import subprocess
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


SUPPORTED_LANGUAGES = {
    "ar": "Arabic",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "fi": "Finnish",
    "fr": "French",
    "he": "Hebrew",
    "hi": "Hindi",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "ms": "Malay",
    "nl": "Dutch",
    "no": "Norwegian",
    "pl": "Polish",
    "pt": "Portuguese",
    "ru": "Russian",
    "sv": "Swedish",
    "sw": "Swahili",
    "tr": "Turkish",
    "zh": "Chinese",
}

MODEL_OPTIONS = {
    "multilingual-v3": {
        "label": "Multilingual V3",
        "description": "Best all-round quality and 23-language voice cloning",
        "languages": list(SUPPORTED_LANGUAGES),
    },
    "turbo": {
        "label": "Turbo",
        "description": "Fast, expressive English with performance tags",
        "languages": ["en"],
    },
    "nano": {
        "label": "Nano",
        "description": "Lightweight English model, suitable for CPU",
        "languages": ["en"],
    },
}


@dataclass(slots=True)
class GenerationOptions:
    model: str
    language: str
    exaggeration: float
    cfg_weight: float
    temperature: float


def split_text(text: str, max_chars: int = 420) -> list[str]:
    """Split long scripts on sentence boundaries without losing text."""
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []

    sentences = re.split(r"(?<=[.!?。！？])\s+", cleaned)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            pieces = re.findall(rf".{{1,{max_chars}}}(?:\s+|$)", sentence + " ")
        else:
            pieces = [sentence]
        for piece in pieces:
            piece = piece.strip()
            candidate = f"{current} {piece}".strip()
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks


def normalize_reference(source: Path, destination: Path) -> None:
    """Convert browser/mobile uploads to a clean mono WAV reference."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None and os.name == "nt":
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            matches = list(
                (Path(local_app_data) / "Microsoft" / "WinGet" / "Packages").glob(
                    "Gyan.FFmpeg*/*/bin/ffmpeg.exe"
                )
            )
            if matches:
                ffmpeg = str(matches[0])

    if ffmpeg is None:
        if source.suffix.lower() != ".wav":
            raise ValueError("FFmpeg is required for non-WAV uploads. Install FFmpeg or use Docker.")
        try:
            with wave.open(str(source), "rb") as audio:
                if audio.getnchannels() < 1 or audio.getframerate() < 8000:
                    raise ValueError("The WAV reference is not a valid speech recording.")
        except (wave.Error, EOFError) as exc:
            raise ValueError("The WAV reference could not be decoded.") from exc
        shutil.copyfile(source, destination)
        return

    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "24000",
        "-af",
        "highpass=f=60,lowpass=f=11000,loudnorm=I=-20:TP=-2:LRA=11",
        str(destination),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise ValueError("The reference audio could not be decoded. Try WAV, MP3, M4A, or WebM.")


class ModelManager:
    """Loads one large model at a time and serializes GPU inference."""

    def __init__(self, device: str = "auto") -> None:
        self.requested_device = device
        self.device = device if device != "auto" else "unresolved"
        self._model_name: str | None = None
        self._model = None
        self._lock = threading.Lock()

    @property
    def loaded_model(self) -> str | None:
        return self._model_name

    def _resolve_device(self) -> str:
        import torch

        if self.requested_device != "auto":
            return self.requested_device
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _load(self, model_name: str):
        if self._model_name == model_name and self._model is not None:
            return self._model

        import gc
        import torch

        self._model = None
        self._model_name = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        self.device = self._resolve_device()
        if model_name == "multilingual-v3":
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS

            model = ChatterboxMultilingualTTS.from_pretrained(
                device=self.device, t3_model="v3"
            )
        elif model_name in {"turbo", "nano"}:
            from chatterbox.tts_turbo import ChatterboxTurboTTS

            model = ChatterboxTurboTTS.from_pretrained(
                device=self.device, nano=model_name == "nano"
            )
        else:
            raise ValueError(f"Unknown model: {model_name}")

        self._model = model
        self._model_name = model_name
        return model

    def generate(
        self,
        text: str,
        reference_path: Path,
        output_path: Path,
        options: GenerationOptions,
        progress: Callable[[int, int], None] | None = None,
    ) -> None:
        import torch
        import torchaudio

        if options.model not in MODEL_OPTIONS:
            raise ValueError("Unsupported voice model")
        if options.language not in MODEL_OPTIONS[options.model]["languages"]:
            raise ValueError("The selected model does not support that language")

        chunks = split_text(text)
        with self._lock, torch.inference_mode():
            model = self._load(options.model)
            generated = []
            for index, chunk in enumerate(chunks, start=1):
                common = {
                    "audio_prompt_path": str(reference_path),
                    "temperature": options.temperature,
                }
                if options.model == "multilingual-v3":
                    wav = model.generate(
                        chunk,
                        language_id=options.language,
                        exaggeration=options.exaggeration,
                        cfg_weight=options.cfg_weight,
                        **common,
                    )
                else:
                    wav = model.generate(chunk, **common)
                generated.append(wav.cpu())
                if index < len(chunks):
                    generated.append(torch.zeros((1, int(model.sr * 0.28))))
                if progress:
                    progress(index, len(chunks))

            combined = torch.cat(generated, dim=-1)
            torchaudio.save(str(output_path), combined, model.sr)


class MockEngine:
    """Tiny offline stand-in used only to test the product flow."""

    device = "mock"
    loaded_model = "mock"

    def generate(
        self,
        text: str,
        reference_path: Path,
        output_path: Path,
        options: GenerationOptions,
        progress: Callable[[int, int], None] | None = None,
    ) -> None:
        del reference_path, options
        sample_rate = 24000
        duration = min(max(len(text) / 18, 1.2), 12)
        frames = int(sample_rate * duration)
        with wave.open(str(output_path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(sample_rate)
            for i in range(frames):
                envelope = min(1.0, i / 1000, (frames - i) / 1000)
                value = int(4200 * envelope * math.sin(2 * math.pi * 190 * i / sample_rate))
                audio.writeframesraw(struct.pack("<h", value))
        if progress:
            progress(1, 1)


def create_engine(device: str, engine_name: str):
    if engine_name == "mock" or os.getenv("VOICEFORGE_ENGINE") == "mock":
        return MockEngine()
    return ModelManager(device=device)

