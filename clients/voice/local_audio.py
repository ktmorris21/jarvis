"""Offline WAV responses, synchronized once from Core's selected ElevenLabs voice.

No live speech generation is performed for local commands. The sync command
fetches a fixed allowlist and validates every WAV before replacing cache files.
"""
import argparse
import asyncio
import base64
import hashlib
import io
import json
import os
import sys
import wave
from pathlib import Path

import httpx

from local_commands import PROMPTS
from boot_notice import BOOT_GREETING

DEFAULT_CACHE = Path(__file__).resolve().parents[2] / "cache" / "local_voice"
DEFAULT_CORE_URL = "https://jarvis-production-110e.up.railway.app"

LOCAL_REPLIES = frozenset({
    BOOT_GREETING,
    "I'm here.",
    *(pair[0] for pair in PROMPTS.values()),
    "Stop requested.",
    "Stop command failed. Use the physical power switch.",
    "Motors armed.",
    "Motors disarmed.",
    "I couldn't arm the motors. Check the drive service.",
    "Motor disarm failed. Use the physical power switch.",
    "Rebooting.",
    "Shutting down.",
    "Power command failed.",
    "Starting update.",
    "Local command failed.",
    "Uploading diagnostics.",
    "Diagnostics uploaded.",
    "Diagnostic upload failed.",
})

def cache_dir():
    return Path(os.environ.get("JARVIS_LOCAL_AUDIO_CACHE", str(DEFAULT_CACHE)))

def cache_file(text):
    if text not in LOCAL_REPLIES:
        return None
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return cache_dir() / (digest + ".wav")

def wav_is_valid_bytes(data):
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            frames, rate = wav.getnframes(), wav.getframerate()
            return (frames > 0 and frames / rate <= 30
                    and rate == 16000 and wav.getnchannels() == 1
                    and wav.getsampwidth() == 2)
    except (OSError, EOFError, wave.Error, ValueError, ZeroDivisionError):
        return False

def valid_wav(path):
    try:
        return path.is_file() and wav_is_valid_bytes(path.read_bytes())
    except OSError:
        return False

def sync(*, url, token):
    if not token:
        raise RuntimeError("JARVIS_INTERFACE_TOKEN is required for sync")
    base = url.rstrip("/")
    headers = {"X-Jarvis-Token": token}
    # Make all network calls before installing any new clip. Never replace the
    # working cache with a partially downloaded or mismatched voice pack.
    with httpx.Client(timeout=65) as client:
        response = client.get(base + "/local-audio/manifest", headers=headers)
        response.raise_for_status()
        manifest = response.json()
        if manifest.get("provider") != "elevenlabs" or set(manifest.get("phrases", [])) != LOCAL_REPLIES:
            raise RuntimeError("Core's selected provider or phrase manifest does not match Pi")
        downloads = {}
        for phrase in sorted(LOCAL_REPLIES):
            response = client.post(base + "/local-audio/render",
                                   json={"phrase": phrase}, headers=headers)
            response.raise_for_status()
            payload = response.json()
            if payload.get("phrase") != phrase:
                raise RuntimeError("Mismatched rendered phrase")
            data = base64.b64decode(payload["wav_base64"], validate=True)
            if len(data) > 1_500_000 or not wav_is_valid_bytes(data):
                raise RuntimeError("Invalid or oversized WAV for " + repr(phrase))
            downloads[phrase] = data
            print("[LOCAL AUDIO] Downloaded " + repr(phrase), flush=True)
    target = cache_dir()
    target.mkdir(parents=True, exist_ok=True)
    for phrase, data in downloads.items():
        path = cache_file(phrase)
        temp = path.with_suffix(".tmp")
        try:
            temp.write_bytes(data)
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
    metadata = {key: manifest[key] for key in ("provider", "voice_id", "model")}
    metadata["phrases"] = sorted(LOCAL_REPLIES)
    temp = target / "manifest.tmp"
    temp.write_text(json.dumps(metadata, indent=2) + "\n")
    temp.replace(target / "manifest.json")
    print("[LOCAL AUDIO] Synced " + str(len(downloads)) +
          " phrases; voice " + str(metadata["voice_id"]), flush=True)

async def play_local_response(text, *, device, fallback=None):
    """Play an approved local WAV. No live TTS fallback for local controls."""
    path = cache_file(text)
    if path is None or not valid_wav(path):
        raise FileNotFoundError("Missing synchronized local voice clip: " + repr(text))
    player = await asyncio.create_subprocess_exec("aplay", "-q", "-D", device, str(path))
    if await player.wait():
        raise RuntimeError("Local WAV playback failed: " + repr(text))
    print("[LOCAL AUDIO] Cache hit: " + repr(text), flush=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["sync"])
    parser.add_argument("--url", default=os.environ.get("JARVIS_CORE_URL", DEFAULT_CORE_URL))
    parser.add_argument("--token", default=os.environ.get("JARVIS_INTERFACE_TOKEN"))
    args = parser.parse_args()
    sync(url=args.url, token=args.token)

if __name__ == "__main__":
    main()
