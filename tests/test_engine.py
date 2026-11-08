from app.engine import MODEL_OPTIONS, SUPPORTED_LANGUAGES, VOICE_OPTIONS, split_text


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
    assert len([voice for voice in VOICE_OPTIONS.values() if voice["engine"] == "kokoro"]) >= 4
    assert VOICE_OPTIONS["clone"]["engine"] == "chatterbox"
    assert VOICE_OPTIONS["global"]["engine"] == "chatterbox-default"
    assert set(VOICE_OPTIONS["global"]["languages"]) == set(SUPPORTED_LANGUAGES)

