import shutil
import wave

import pytest

from app.engine import (
    MODEL_OPTIONS,
    SUPPORTED_LANGUAGES,
    VOICE_OPTIONS,
    adjust_audio_speed,
    split_text,
)


def test_split_text_keeps_short_script_together():
    assert split_text("A short sentence. Another one.") == ["A short sentence. Another one."]


def test_split_text_respects_chunk_size():
    text = "First sentence is here. Second sentence is longer. Third sentence finishes."
    chunks = split_text(text, max_chars=35)
    assert len(chunks) >= 2
    assert all(len(chunk) <= 35 for chunk in chunks)
    assert " ".join(chunks) == text


def test_all_model_languages_are_declared():
    for model in MODEL_OPTIONS.values():
        assert set(model["languages"]).issubset(SUPPORTED_LANGUAGES)


def test_all_voice_languages_are_declared():
    for voice in VOICE_OPTIONS.values():
        assert set(voice["languages"]).issubset(SUPPORTED_LANGUAGES)


def test_ready_voice_catalog_and_clone_are_available():
    assert len([voice for voice in VOICE_OPTIONS.values() if voice["engine"] == "kokoro"]) >= 25
    assert VOICE_OPTIONS["clone"]["engine"] == "chatterbox"
    assert VOICE_OPTIONS["global"]["engine"] == "chatterbox-default"
    assert set(VOICE_OPTIONS["global"]["languages"]) == set(SUPPORTED_LANGUAGES)
    assert all(voice.get("style") for voice in VOICE_OPTIONS.values())
    assert all(voice.get("gender") for voice in VOICE_OPTIONS.values())
    assert all(voice.get("use_cases") for voice in VOICE_OPTIONS.values())


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
def test_speed_control_changes_duration_without_corrupting_wav(tmp_path):
    path = tmp_path / "voice.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\x00\x00" * 24000 * 2)

    adjust_audio_speed(path, 1.25)

    with wave.open(str(path), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
    assert 1.5 < duration < 1.7

