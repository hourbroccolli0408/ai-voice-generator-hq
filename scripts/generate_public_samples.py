from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from app.engine import GenerationOptions, ModelManager


SAMPLES = {
    "heart": "Every good story deserves a voice that makes people stop, listen, and remember.",
    "michael": "Clear narration turns complex ideas into stories people can follow.",
    "emma": "From product demos to podcasts, a polished voice gives every message confidence.",
    "george": "Create, refine, and publish professional voiceovers without leaving your browser.",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the public AI Voice HQ samples.")
    parser.add_argument("--force", action="store_true", help="Replace existing MP3 files.")
    args = parser.parse_args()

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("FFmpeg is required to create the public MP3 samples.")

    output_dir = Path("app/static/audio/voices")
    output_dir.mkdir(parents=True, exist_ok=True)
    engine = ModelManager(device="cpu")

    for voice, script in SAMPLES.items():
        mp3_path = output_dir / f"{voice}.mp3"
        if mp3_path.exists() and not args.force:
            print(f"Keeping {mp3_path}", flush=True)
            continue

        wav_path = output_dir / f"{voice}.wav"
        print(f"Generating {voice}", flush=True)
        engine.generate(
            script,
            reference_path=None,
            output_path=wav_path,
            options=GenerationOptions(
                model="turbo",
                language="en",
                exaggeration=0.5,
                cfg_weight=0.5,
                temperature=0.8,
                voice=voice,
                speed=1.0,
            ),
        )
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(wav_path),
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "96k",
                str(mp3_path),
            ],
            check=True,
            capture_output=True,
        )
        wav_path.unlink()
        print(f"Wrote {mp3_path}", flush=True)


if __name__ == "__main__":
    main()
