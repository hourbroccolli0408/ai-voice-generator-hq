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

