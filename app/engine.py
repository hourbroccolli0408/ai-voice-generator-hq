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

TRANSLATION_SOURCE_LANGUAGES = {
    "af", "am", "ar", "ast", "az", "ba", "be", "bg", "bn", "br", "bs", "ca",
    "ceb", "cs", "cy", "da", "de", "el", "en", "es", "et", "fa", "ff", "fi",
    "fr", "fy", "ga", "gd", "gl", "gu", "ha", "he", "hi", "hr", "ht", "hu",
    "hy", "id", "ig", "ilo", "is", "it", "ja", "jv", "ka", "kk", "km", "kn",
    "ko", "lb", "lg", "ln", "lo", "lt", "lv", "mg", "mk", "ml", "mn", "mr",
    "ms", "my", "ne", "nl", "no", "ns", "oc", "or", "pa", "pl", "ps", "pt",
    "ro", "ru", "sd", "si", "sk", "sl", "so", "sq", "sr", "ss", "su", "sv",
    "sw", "ta", "th", "tl", "tn", "tr", "uk", "ur", "uz", "vi", "wo", "xh",
    "yi", "yo", "zh", "zu",
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

VOICE_OPTIONS = {
    "global": {
        "label": "Global Narrator",
        "description": "Natural house voice for every supported language",
        "accent": "Multilingual",
        "engine": "chatterbox-default",
        "languages": list(SUPPORTED_LANGUAGES),
    },
    "heart": {
        "label": "Heart",
        "description": "Warm, natural American voice",
        "accent": "American",
        "gender": "Female",
        "style": "Warm",
        "use_cases": ["Narration", "Wellness", "Audiobooks"],
        "engine": "kokoro",
        "engine_voice": "af_heart",
        "language_code": "a",
        "languages": ["en"],
    },
    "bella": {
        "label": "Bella",
        "description": "Expressive American voice",
        "accent": "American",
        "gender": "Female",
        "style": "Expressive",
        "use_cases": ["Advertising", "Social", "Characters"],
        "engine": "kokoro",
        "engine_voice": "af_bella",
        "language_code": "a",
        "languages": ["en"],
    },
    "michael": {
        "label": "Michael",
        "description": "Grounded American voice",
        "accent": "American",
        "gender": "Male",
        "style": "Grounded",
        "use_cases": ["Documentary", "Corporate", "Audiobooks"],
        "engine": "kokoro",
        "engine_voice": "am_michael",
        "language_code": "a",
        "languages": ["en"],
    },
    "emma": {
        "label": "Emma",
        "description": "Clear, polished British voice",
        "accent": "British",
        "gender": "Female",
        "style": "Polished",
        "use_cases": ["E-learning", "Corporate", "Narration"],
        "engine": "kokoro",
        "engine_voice": "bf_emma",
        "language_code": "b",
        "languages": ["en"],
    },
    "george": {
        "label": "George",
        "description": "Calm British voice",
        "accent": "British",
        "gender": "Male",
        "style": "Calm",
        "use_cases": ["Documentary", "Audiobooks", "News"],
        "engine": "kokoro",
        "engine_voice": "bm_george",
        "language_code": "b",
        "languages": ["en"],
    },
    "nicole": {
        "label": "Nicole",
        "description": "Confident American narrator",
        "accent": "American",
        "gender": "Female",
        "style": "Confident",
        "use_cases": ["Advertising", "News", "Presentations"],
        "engine": "kokoro",
        "engine_voice": "af_nicole",
        "language_code": "a",
        "languages": ["en"],
    },
    "clone": {
        "label": "Clone my voice",
        "description": "Upload or record an authorized voice sample",
        "accent": "Custom",
        "gender": "Custom",
        "style": "Custom",
        "use_cases": ["Brand voice", "Personal voice"],
        "engine": "chatterbox",
        "languages": list(SUPPORTED_LANGUAGES),
    },
}

# Kokoro's Apache-2.0 voice pack gives us a credible ready-made catalogue without
# pretending that minor parameter changes are separate voices. The six original
# launch voices above remain stable so existing saved jobs never change identity.
VOICE_OPTIONS.update(
    {
        "alloy": {
            "label": "Alloy", "description": "Balanced and conversational American voice",
            "accent": "American", "gender": "Female", "style": "Conversational",
            "use_cases": ["Support", "Podcasts", "E-learning"], "engine": "kokoro",
            "engine_voice": "af_alloy", "language_code": "a", "languages": ["en"],
        },
        "aoede": {
            "label": "Aoede", "description": "Bright American storyteller",
            "accent": "American", "gender": "Female", "style": "Bright",
            "use_cases": ["Stories", "Social", "Advertising"], "engine": "kokoro",
            "engine_voice": "af_aoede", "language_code": "a", "languages": ["en"],
        },
        "jessica": {
            "label": "Jessica", "description": "Friendly, clear American presenter",
            "accent": "American", "gender": "Female", "style": "Friendly",
            "use_cases": ["Presentations", "Support", "E-learning"], "engine": "kokoro",
            "engine_voice": "af_jessica", "language_code": "a", "languages": ["en"],
        },
        "kore": {
            "label": "Kore", "description": "Direct American voice with a modern edge",
            "accent": "American", "gender": "Female", "style": "Direct",
            "use_cases": ["Technology", "Advertising", "News"], "engine": "kokoro",
            "engine_voice": "af_kore", "language_code": "a", "languages": ["en"],
        },
        "nova": {
            "label": "Nova", "description": "Energetic American creator voice",
            "accent": "American", "gender": "Female", "style": "Energetic",
            "use_cases": ["Social", "Advertising", "Podcasts"], "engine": "kokoro",
            "engine_voice": "af_nova", "language_code": "a", "languages": ["en"],
        },
        "river": {
            "label": "River", "description": "Relaxed and thoughtful American voice",
            "accent": "American", "gender": "Female", "style": "Relaxed",
            "use_cases": ["Wellness", "Podcasts", "Narration"], "engine": "kokoro",
            "engine_voice": "af_river", "language_code": "a", "languages": ["en"],
        },
        "sarah": {
            "label": "Sarah", "description": "Warm American explainer voice",
            "accent": "American", "gender": "Female", "style": "Reassuring",
            "use_cases": ["E-learning", "Healthcare", "Support"], "engine": "kokoro",
            "engine_voice": "af_sarah", "language_code": "a", "languages": ["en"],
        },
        "sky": {
            "label": "Sky", "description": "Youthful American voice for short-form content",
            "accent": "American", "gender": "Female", "style": "Youthful",
            "use_cases": ["Social", "Characters", "Advertising"], "engine": "kokoro",
            "engine_voice": "af_sky", "language_code": "a", "languages": ["en"],
        },
        "adam": {
            "label": "Adam", "description": "Deep American cinematic narrator",
            "accent": "American", "gender": "Male", "style": "Cinematic",
            "use_cases": ["Trailers", "Documentary", "Audiobooks"], "engine": "kokoro",
            "engine_voice": "am_adam", "language_code": "a", "languages": ["en"],
        },
        "echo": {
            "label": "Echo", "description": "Clean American technology voice",
            "accent": "American", "gender": "Male", "style": "Modern",
            "use_cases": ["Technology", "Support", "Presentations"], "engine": "kokoro",
            "engine_voice": "am_echo", "language_code": "a", "languages": ["en"],
        },
        "eric": {
            "label": "Eric", "description": "Approachable American professional",
            "accent": "American", "gender": "Male", "style": "Professional",
            "use_cases": ["Corporate", "Support", "E-learning"], "engine": "kokoro",
            "engine_voice": "am_eric", "language_code": "a", "languages": ["en"],
        },
        "fenrir": {
            "label": "Fenrir", "description": "Bold American character voice",
            "accent": "American", "gender": "Male", "style": "Bold",
            "use_cases": ["Gaming", "Characters", "Trailers"], "engine": "kokoro",
            "engine_voice": "am_fenrir", "language_code": "a", "languages": ["en"],
        },
        "liam": {
            "label": "Liam", "description": "Easygoing American conversational voice",
            "accent": "American", "gender": "Male", "style": "Easygoing",
            "use_cases": ["Podcasts", "Support", "Social"], "engine": "kokoro",
            "engine_voice": "am_liam", "language_code": "a", "languages": ["en"],
        },
        "onyx": {
            "label": "Onyx", "description": "Authoritative American announcer",
            "accent": "American", "gender": "Male", "style": "Authoritative",
            "use_cases": ["News", "Advertising", "Documentary"], "engine": "kokoro",
            "engine_voice": "am_onyx", "language_code": "a", "languages": ["en"],
        },
        "puck": {
            "label": "Puck", "description": "Playful American character voice",
            "accent": "American", "gender": "Male", "style": "Playful",
            "use_cases": ["Characters", "Gaming", "Social"], "engine": "kokoro",
            "engine_voice": "am_puck", "language_code": "a", "languages": ["en"],
        },
        "alice": {
            "label": "Alice", "description": "Elegant British storyteller",
            "accent": "British", "gender": "Female", "style": "Elegant",
            "use_cases": ["Audiobooks", "Luxury", "Documentary"], "engine": "kokoro",
            "engine_voice": "bf_alice", "language_code": "b", "languages": ["en"],
        },
        "isabella": {
            "label": "Isabella", "description": "Warm British lifestyle voice",
            "accent": "British", "gender": "Female", "style": "Warm",
            "use_cases": ["Lifestyle", "Advertising", "Narration"], "engine": "kokoro",
            "engine_voice": "bf_isabella", "language_code": "b", "languages": ["en"],
        },
        "lily": {
            "label": "Lily", "description": "Soft British voice for calm narration",
            "accent": "British", "gender": "Female", "style": "Soft",
            "use_cases": ["Wellness", "Audiobooks", "E-learning"], "engine": "kokoro",
            "engine_voice": "bf_lily", "language_code": "b", "languages": ["en"],
        },
        "daniel": {
            "label": "Daniel", "description": "Assured British professional voice",
            "accent": "British", "gender": "Male", "style": "Assured",
            "use_cases": ["Corporate", "News", "Presentations"], "engine": "kokoro",
            "engine_voice": "bm_daniel", "language_code": "b", "languages": ["en"],
        },
        "fable": {
            "label": "Fable", "description": "Expressive British story voice",
            "accent": "British", "gender": "Male", "style": "Expressive",
            "use_cases": ["Audiobooks", "Gaming", "Characters"], "engine": "kokoro",
            "engine_voice": "bm_fable", "language_code": "b", "languages": ["en"],
        },
        "lewis": {
            "label": "Lewis", "description": "Measured British documentary voice",
            "accent": "British", "gender": "Male", "style": "Measured",
            "use_cases": ["Documentary", "E-learning", "Corporate"], "engine": "kokoro",
            "engine_voice": "bm_lewis", "language_code": "b", "languages": ["en"],
        },
    }
)

for _voice in VOICE_OPTIONS.values():
    _voice.setdefault("gender", "Neutral")
    _voice.setdefault("style", "Natural")
    _voice.setdefault("use_cases", ["Voiceover"])


@dataclass(slots=True)
class GenerationOptions:
    model: str
    language: str
    exaggeration: float
    cfg_weight: float
    temperature: float
    voice: str = "clone"
    speed: float = 1.0


def adjust_audio_speed(path: Path, speed: float) -> None:
    """Apply studio pacing without changing pitch."""
    if abs(speed - 1.0) < 0.01:
        return
    if not 0.75 <= speed <= 1.25:
        raise ValueError("Speaking speed must be between 0.75x and 1.25x")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("Speaking-speed control requires FFmpeg")
    temporary = path.with_name(f"{path.stem}-paced{path.suffix}")
    result = subprocess.run(
        [ffmpeg, "-y", "-i", str(path), "-filter:a", f"atempo={speed}", str(temporary)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0 or not temporary.exists():
        temporary.unlink(missing_ok=True)
        raise RuntimeError("Could not apply the selected speaking speed")
    temporary.replace(path)


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
        self._translator = None
        self._translator_tokenizer = None

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
        if model_name.startswith("kokoro-"):
            from kokoro import KPipeline

            language_code = model_name.removeprefix("kokoro-")
            model = KPipeline(
                lang_code=language_code,
                repo_id="hexgrad/Kokoro-82M",
                device=self.device,
            )
        elif model_name == "multilingual-v3":
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
        reference_path: Path | None,
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
        if options.voice not in VOICE_OPTIONS:
            raise ValueError("Unsupported voice")

        voice = VOICE_OPTIONS[options.voice]
        is_clone = voice["engine"] == "chatterbox"
        is_chatterbox = voice["engine"] in {"chatterbox", "chatterbox-default"}
        if is_clone and reference_path is None:
            raise ValueError("A reference recording is required to clone a voice")
        if options.language not in voice["languages"]:
            raise ValueError("The selected voice does not support that language")

        chunks = split_text(text)
        with self._lock, torch.inference_mode():
            model_name = (
                options.model
                if is_clone
                else "multilingual-v3"
                if is_chatterbox
                else f"kokoro-{voice['language_code']}"
            )
            model = self._load(model_name)
            generated = []
            for index, chunk in enumerate(chunks, start=1):
                if is_chatterbox:
                    common = {
                        "temperature": options.temperature,
                    }
                    if reference_path is not None:
                        common["audio_prompt_path"] = str(reference_path)
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
                else:
                    results = list(model(chunk, voice=voice["engine_voice"]))
                    for result_index, result in enumerate(results):
                        if result.audio is None:
                            continue
                        generated.append(result.audio.cpu().reshape(1, -1))
                        if result_index < len(results) - 1:
                            generated.append(torch.zeros((1, int(24000 * 0.08))))
                if index < len(chunks):
                    sample_rate = model.sr if is_chatterbox else 24000
                    generated.append(torch.zeros((1, int(sample_rate * 0.28))))
                if progress:
                    progress(index, len(chunks))

            if not generated:
                raise RuntimeError("The speech engine did not return any audio")
            combined = torch.cat(generated, dim=-1)
            sample_rate = model.sr if is_chatterbox else 24000
            if not is_chatterbox:
                import perth

                watermarker = perth.PerthImplicitWatermarker()
                marked = watermarker.apply_watermark(
                    combined.squeeze(0).numpy(), sample_rate=sample_rate
                )
                combined = torch.from_numpy(marked).reshape(1, -1)
            torchaudio.save(str(output_path), combined, sample_rate)
            adjust_audio_speed(output_path, options.speed)

    def translate(
        self,
        text: str,
        source_language: str,
        target_languages: list[str],
    ) -> dict[str, str]:
        import torch
        from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer

        if source_language not in TRANSLATION_SOURCE_LANGUAGES:
            raise ValueError("The detected source language is not supported")
        invalid_targets = set(target_languages) - set(SUPPORTED_LANGUAGES)
        if invalid_targets:
            raise ValueError("One or more target languages are not supported")

        with self._lock, torch.inference_mode():
            if self._translator is None or self._translator_tokenizer is None:
                self.device = self._resolve_device()
                self._translator_tokenizer = M2M100Tokenizer.from_pretrained(
                    "facebook/m2m100_418M"
                )
                dtype = torch.float16 if self.device == "cuda" else torch.float32
                self._translator = M2M100ForConditionalGeneration.from_pretrained(
                    "facebook/m2m100_418M", torch_dtype=dtype
                ).to(self.device)
                self._translator.eval()

            tokenizer = self._translator_tokenizer
            tokenizer.src_lang = source_language
            chunks = split_text(text, max_chars=700)
            translations = {language: [] for language in target_languages}
            for chunk in chunks:
                if source_language in translations:
                    translations[source_language].append(chunk)
                encoded = tokenizer(
                    chunk,
                    return_tensors="pt",
                    truncation=True,
                    max_length=512,
                ).to(self.device)
                for language in target_languages:
                    if language == source_language:
                        continue
                    generated = self._translator.generate(
                        **encoded,
                        forced_bos_token_id=tokenizer.get_lang_id(language),
                        max_new_tokens=512,
                    )
                    translations[language].append(
                        tokenizer.batch_decode(generated, skip_special_tokens=True)[0]
                    )
            return {language: " ".join(parts) for language, parts in translations.items()}


class MockEngine:
    """Tiny offline stand-in used only to test the product flow."""

    device = "mock"
    loaded_model = "mock"

    def generate(
        self,
        text: str,
        reference_path: Path | None,
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

    def translate(
        self,
        text: str,
        source_language: str,
        target_languages: list[str],
    ) -> dict[str, str]:
        return {
            language: text if language == source_language else f"[{language}] {text}"
            for language in target_languages
        }


def create_engine(device: str, engine_name: str):
    if engine_name == "mock" or os.getenv("VOICEFORGE_ENGINE") == "mock":
        return MockEngine()
    return ModelManager(device=device)

