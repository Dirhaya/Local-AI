"""Explicit setup-time download. Never invoked by the running app."""
import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Download a multilingual faster-whisper model for offline dictation and meeting transcription.")
    parser.add_argument("--model", choices=["tiny", "base", "small", "medium"], default="base")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    from faster_whisper.utils import download_model
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "SultanLocalAI" / "models"
    path = (args.output or root / ("whisper-" + args.model)).expanduser().resolve()
    download_model(args.model, output_dir=str(path))
    print("\nDownloaded speech model. In the app, open Settings and paste this folder into Speech model path:\n")
    print(path)
    print("\nThe app uses this folder offline. Try --model small for better recognition if your computer has enough RAM.")


if __name__ == "__main__":
    main()
