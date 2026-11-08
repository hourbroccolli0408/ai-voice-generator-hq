# AI Voice Generator HQ

AI Voice Generator HQ is a consent-first AI voiceover service. Choose a ready-made voice or
provide a 6–30 second reference clip from an authorized speaker, paste a script, and generate
downloadable, watermarked WAVs in one language or up to five languages at once.

The default backend uses **Kokoro 82M** for ready-made English voices, **Chatterbox
Multilingual V3** for the Global Narrator and 23-language zero-shot voice cloning, and
**M2M100 418M** for 100-language script translation. Turbo and Nano are included for faster
English cloning. Generated audio receives a PerTh provenance watermark.

> Only clone your own voice or a voice you have explicit permission to use. VoiceForge
> requires a consent attestation whenever a user clones a voice. Production mode includes Supabase
> authentication and a transaction-safe character credit ledger. Rate limiting and payment
> webhooks remain required before a fully public launch.

## What is included

- Browser recording and drag-and-drop audio uploads
- Six ready-made American and British voices plus a multilingual Global Narrator
- Automatic source-language detection and up to five translated voiceovers per job
- Multilingual V3, English Turbo, and CPU-friendly Nano model choices
- Long-script chunking and a single-worker generation queue
- Local history, playback, and WAV downloads
- Expression, voice-guidance, and variation controls
- Docker GPU and CPU launch configurations
- Built-in synthetic-audio watermarking from Chatterbox
- A mock engine for fast UI development without downloading model weights
- Supabase-compatible authentication and Postgres persistence
- Character credits (source characters × output languages) with automatic failure refunds
- Optional private Cloudflare R2 audio storage
- A separate RunPod Serverless GPU worker

## Recommended hardware

- **Best experience:** NVIDIA GPU with at least 8 GB VRAM, recent drivers, and Docker
  Desktop/Engine with NVIDIA Container Toolkit support.
- **CPU mode:** 8 modern CPU cores and 16 GB RAM. Select Nano for reasonable speed.
- **Disk:** allow roughly 5–10 GB for the container, Python packages, and cached models.

The first generation is slower because the selected model downloads once into
`.cache/huggingface`.

## Start with an NVIDIA GPU

1. Copy `.env.example` to `.env`.
2. From this directory, run:

   ```powershell
   docker compose up --build
   ```

3. Open [http://localhost:8000](http://localhost:8000).

## Start in CPU mode

```powershell
docker compose -f docker-compose.cpu.yml up --build
```

Choose **Nano** in the interface. Multilingual V3 can run on CPU but will be much slower.

## Native Windows CPU setup

This machine is configured for native CPU inference with Python 3.11 and FFmpeg. To
restart VoiceForge after a reboot, double-click **`Start VoiceForge.cmd`**. It launches
the local server invisibly in the background and opens the studio in your browser.

Nano is the recommended model on this machine. The multilingual model remains available,
but generation will be significantly slower without an NVIDIA GPU.

## Preview the interface without the AI model

This exercises uploads, the queue, history, playback, and downloads using a synthetic
tone instead of cloned speech:

```powershell
$env:VOICEFORGE_ENGINE="mock"
python -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"
.\.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000
```

For a non-Windows shell, activate the virtual environment with
`source .venv/bin/activate` and use `uvicorn app.main:app`.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `VOICEFORGE_DEVICE` | `auto` | `cuda`, `mps`, `cpu`, or automatic detection |
| `VOICEFORGE_ENGINE` | `chatterbox` | Use `mock` only for development |
| `VOICEFORGE_MAX_TEXT_CHARS` | `5000` | Maximum script length per job |
| `VOICEFORGE_MAX_UPLOAD_MB` | `30` | Maximum reference-audio upload |
| `VOICEFORGE_WORKERS` | `1` | Concurrent workers; keep at 1 for one GPU |
| `HF_TOKEN` | unset | Optional Hugging Face token |

Generated audio and job metadata live under `data/jobs`; normalized reference clips live
under `data/uploads`. Remove those folders' contents when you want to erase local data.

For the public beta architecture and launch sequence, see [DEPLOYMENT.md](DEPLOYMENT.md).
Third-party model licenses and attribution are listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Model and maintenance note

Chatterbox's code and released models remain available under permissive terms, but its
upstream repository has been archived and unsupported since August 2026. VoiceForge keeps
all model-specific code in `app/engine.py`, so another engine can be added without changing
the API or interface.

## Development checks

```powershell
python -m pytest
python -m ruff check app tests
```

