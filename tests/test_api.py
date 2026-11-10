import importlib
import time
import wave
from pathlib import Path

from fastapi.testclient import TestClient


def make_reference(path: Path, seconds: int = 6) -> Path:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\x00\x00" * 24000 * seconds)
    return path


def test_health_and_config(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICEFORGE_ENGINE", "mock")
    monkeypatch.setenv("VOICEFORGE_DATA_DIR", str(tmp_path / "data"))
    import app.config
    import app.main

    importlib.reload(app.config)
    module = importlib.reload(app.main)
    with TestClient(module.app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["engine"] == "mock"
        config = client.get("/api/config")
        assert "multilingual-v3" in config.json()["models"]
        assert "heart" in config.json()["voices"]
        assert "global" in config.json()["voices"]
        assert "clone" in config.json()["voices"]
        assert config.json()["limits"]["max_translation_targets"] == 5


def test_public_marketing_routes(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICEFORGE_ENGINE", "mock")
    monkeypatch.setenv("VOICEFORGE_DATA_DIR", str(tmp_path / "data"))
    import app.config
    import app.main

    importlib.reload(app.config)
    module = importlib.reload(app.main)
    with TestClient(module.app) as client:
        for route in ("/", "/pricing", "/studio", "/privacy", "/terms"):
            response = client.get(route)
            assert response.status_code == 200
            assert "AI Voice HQ" in response.text
        home = client.get("/").text
        pricing = client.get("/pricing").text
        assert "FOUNDER PRICING" in pricing
        assert "Hear the quality before you sign up" in home
        assert 'data-marketing-preset="energetic"' in home
        assert '/studio?preset=energetic' in home
        assert "5,000 one-time starter credits" in pricing
        for voice in ("heart", "emma", "michael", "george"):
            sample = client.get(f"/audio/voices/{voice}.mp3")
            assert sample.status_code == 200
            assert sample.headers["content-type"] == "audio/mpeg"


def test_generation_requires_consent(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICEFORGE_ENGINE", "mock")
    monkeypatch.setenv("VOICEFORGE_DATA_DIR", str(tmp_path / "data"))
    import app.config
    import app.main

    importlib.reload(app.config)
    module = importlib.reload(app.main)
    reference = make_reference(tmp_path / "reference.wav")
    with TestClient(module.app) as client, reference.open("rb") as audio:
        response = client.post(
            "/api/generate",
            files={"reference": ("reference.wav", audio, "audio/wav")},
            data={"text": "This should not run.", "consent": "false"},
        )
    assert response.status_code == 400
    assert "consent" in response.json()["detail"].lower()


def test_ready_voice_does_not_require_reference_or_consent(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICEFORGE_ENGINE", "mock")
    monkeypatch.setenv("VOICEFORGE_DATA_DIR", str(tmp_path / "data"))
    import app.config
    import app.main

    importlib.reload(app.config)
    module = importlib.reload(app.main)
    with TestClient(module.app) as client:
        response = client.post(
            "/api/generate",
            data={
                "text": "A ready voice works without a recording.",
                "voice": "heart",
                "model": "multilingual-v3",
                "language": "en",
                "consent": "false",
            },
        )
        assert response.status_code == 202
        job = response.json()
        assert job["voice"] == "heart"
        assert job["voice_label"] == "Heart"
        assert job["voice_source"] == "ready-made"
        for _ in range(100):
            job = client.get(f"/api/jobs/{job['id']}").json()
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.01)
        assert job["status"] == "completed"
        assert job["takes"][0]["label"] == "Take 1"


def test_project_and_task_name_are_saved_with_generation(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICEFORGE_ENGINE", "mock")
    monkeypatch.setenv("VOICEFORGE_DATA_DIR", str(tmp_path / "data"))
    import app.config
    import app.main

    importlib.reload(app.config)
    module = importlib.reload(app.main)
    with TestClient(module.app) as client:
        created = client.post("/api/projects", json={"name": "Launch Campaign"})
        assert created.status_code == 201
        project = created.json()
        response = client.post(
            "/api/generate",
            data={
                "text": "A named project voiceover.",
                "title": "Opening advertisement",
                "project_id": project["id"],
                "voice": "heart",
            },
        )
        assert response.status_code == 202
        job = response.json()
        assert job["title"] == "Opening advertisement"
        assert job["project_id"] == project["id"]
        assert job["project_name"] == "Launch Campaign"
        projects = client.get("/api/projects").json()
        assert projects[0]["job_count"] == 1


def test_two_takes_cost_double_and_each_is_downloadable(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICEFORGE_ENGINE", "mock")
    monkeypatch.setenv("VOICEFORGE_DATA_DIR", str(tmp_path / "data"))
    import app.config
    import app.main

    importlib.reload(app.config)
    module = importlib.reload(app.main)
    script = "Compare two candidate reads."
    with TestClient(module.app) as client:
        starting_credits = client.get("/api/account").json()["credits"]
        response = client.post(
            "/api/generate",
            data={
                "text": script,
                "voice": "alloy",
                "model": "multilingual-v3",
                "language": "en",
                "speed": "1.1",
                "variations": "2",
            },
        )
        assert response.status_code == 202
        job_id = response.json()["id"]
        for _ in range(100):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.01)
        assert job["status"] == "completed"
        assert [take["take"] for take in job["takes"]] == [1, 2]
        assert client.get(f"/api/jobs/{job_id}/audio-url?take=2&download=true").status_code == 200
        ending_credits = client.get("/api/account").json()["credits"]
        assert ending_credits == starting_credits - (len(script) * 2)


def test_generation_rejects_invalid_pacing_and_take_count(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICEFORGE_ENGINE", "mock")
    monkeypatch.setenv("VOICEFORGE_DATA_DIR", str(tmp_path / "data"))
    import app.config
    import app.main

    importlib.reload(app.config)
    module = importlib.reload(app.main)
    with TestClient(module.app) as client:
        too_fast = client.post(
            "/api/generate",
            data={"text": "Test", "voice": "heart", "speed": "1.5"},
        )
        too_many = client.post(
            "/api/generate",
            data={"text": "Test", "voice": "heart", "variations": "3"},
        )
    assert too_fast.status_code == 400
    assert too_many.status_code == 400


def test_mock_generation_completes(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICEFORGE_ENGINE", "mock")
    monkeypatch.setenv("VOICEFORGE_DATA_DIR", str(tmp_path / "data"))
    import app.config
    import app.main

    importlib.reload(app.config)
    module = importlib.reload(app.main)
    reference = make_reference(tmp_path / "reference.wav")
    with TestClient(module.app) as client, reference.open("rb") as audio:
        starting_credits = client.get("/api/account").json()["credits"]
        response = client.post(
            "/api/generate",
            files={"reference": ("reference.wav", audio, "audio/wav")},
            data={
                "text": "A small end-to-end test.",
                "model": "nano",
                "language": "en",
                "voice": "clone",
                "consent": "true",
            },
        )
        assert response.status_code == 202
        job_id = response.json()["id"]
        for _ in range(100):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.01)
        assert job["status"] == "completed"
        audio_response = client.get(job["audio_url"])
        assert audio_response.status_code == 200
        assert audio_response.headers["content-type"] == "audio/wav"
        access_response = client.get(f"/api/jobs/{job_id}/audio-url?download=true")
        assert access_response.status_code == 200
        assert access_response.json()["url"].endswith("/audio?download=true")
        assert access_response.json()["download_name"].endswith(".wav")
        ending_credits = client.get("/api/account").json()["credits"]
        assert ending_credits == starting_credits - len("A small end-to-end test.")


def test_multilingual_generation_creates_one_output_per_language(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICEFORGE_ENGINE", "mock")
    monkeypatch.setenv("VOICEFORGE_DATA_DIR", str(tmp_path / "data"))
    import app.config
    import app.main

    importlib.reload(app.config)
    module = importlib.reload(app.main)
    script = "A clear test of translated voiceovers."
    with TestClient(module.app) as client:
        starting_credits = client.get("/api/account").json()["credits"]
        response = client.post(
            "/api/generate-multilingual",
            data={
                "text": script,
                "source_language": "en",
                "target_languages": "fr,es",
                "voice": "global",
            },
        )
        assert response.status_code == 202
        job_id = response.json()["id"]
        for _ in range(100):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.01)
        assert job["status"] == "completed"
        assert [output["language"] for output in job["outputs"]] == ["fr", "es"]
        assert all("audio_locator" not in output for output in job["outputs"])
        for language in ("fr", "es"):
            access = client.get(
                f"/api/jobs/{job_id}/audio-url?language={language}&download=true"
            )
            assert access.status_code == 200
            assert access.json()["download_name"].endswith(f"-{language}.wav")
        ending_credits = client.get("/api/account").json()["credits"]
        assert ending_credits == starting_credits - (len(script) * 2)


def test_multilingual_clone_still_requires_consent(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICEFORGE_ENGINE", "mock")
    monkeypatch.setenv("VOICEFORGE_DATA_DIR", str(tmp_path / "data"))
    import app.config
    import app.main

    importlib.reload(app.config)
    module = importlib.reload(app.main)
    with TestClient(module.app) as client:
        response = client.post(
            "/api/generate-multilingual",
            data={
                "text": "Translate me.",
                "source_language": "en",
                "target_languages": "fr",
                "voice": "clone",
                "consent": "false",
            },
        )
    assert response.status_code == 400
    assert "consent" in response.json()["detail"].lower()


def test_translation_rejects_english_only_voice(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICEFORGE_ENGINE", "mock")
    monkeypatch.setenv("VOICEFORGE_DATA_DIR", str(tmp_path / "data"))
    import app.config
    import app.main

    importlib.reload(app.config)
    module = importlib.reload(app.main)
    with TestClient(module.app) as client:
        response = client.post(
            "/api/generate-multilingual",
            data={
                "text": "Translate me.",
                "source_language": "en",
                "target_languages": "fr",
                "voice": "heart",
            },
        )
    assert response.status_code == 400
    assert "global narrator" in response.json()["detail"].lower()


def test_saved_voice_lifecycle_and_reuse(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICEFORGE_ENGINE", "mock")
    monkeypatch.setenv("VOICEFORGE_DATA_DIR", str(tmp_path / "data"))
    import app.config
    import app.main

    importlib.reload(app.config)
    module = importlib.reload(app.main)
    reference = make_reference(tmp_path / "saved-reference.wav")
    with TestClient(module.app) as client:
        with reference.open("rb") as audio:
            rejected = client.post(
                "/api/voices",
                files={"reference": ("saved-reference.wav", audio, "audio/wav")},
                data={"name": "My Narrator", "consent": "false"},
            )
        assert rejected.status_code == 400

        with reference.open("rb") as audio:
            created = client.post(
                "/api/voices",
                files={"reference": ("saved-reference.wav", audio, "audio/wav")},
                data={
                    "name": "My Narrator",
                    "accent": "Indian English",
                    "language": "en",
                    "use_tags": "Narration, Podcast",
                    "default_preset": "warm",
                    "consent": "true",
                },
            )
        assert created.status_code == 201
        voice = created.json()
        assert voice["name"] == "My Narrator"
        assert voice["use_tags"] == ["Narration", "Podcast"]
        assert "locator" not in voice
        assert client.get(voice["preview_url"]).status_code == 200

        renamed = client.patch(f"/api/voices/{voice['id']}", json={"name": "Campaign Voice"})
        assert renamed.status_code == 200
        assert renamed.json()["name"] == "Campaign Voice"

        response = client.post(
            "/api/generate",
            data={
                "text": "Reuse my private saved voice.",
                "voice": "clone",
                "saved_voice_id": voice["id"],
                "model": "nano",
                "language": "en",
                "consent": "false",
            },
        )
        assert response.status_code == 202
        job = response.json()
        assert job["voice_source"] == "saved"
        assert job["voice_label"] == "Campaign Voice"
        for _ in range(100):
            job = client.get(f"/api/jobs/{job['id']}").json()
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.01)
        assert job["status"] == "completed"

        voices = client.get("/api/voices").json()
        assert voices[0]["use_count"] == 1
        locator = module.repository.get_saved_voice(voice["id"], "local-development-user")[
            "locator"
        ]
        assert Path(locator).exists()
        deleted = client.delete(f"/api/voices/{voice['id']}")
        assert deleted.status_code == 200
        assert not Path(locator).exists()
        assert client.get("/api/voices").json() == []

