"""Pre-rendered local control responses: no Piper startup on cache hit.

Run `python clients/voice/local_audio.py generate` once on the Pi to build
cached WAV files with the same Piper binary/model used by normal Jarvis TTS.
"""
import asyncio
import hashlib
import os
import subprocess
import sys
import wave
from pathlib import Path

from local_commands import PROMPTS
from boot_notice import BOOT_GREETING

DEFAULT_CACHE = Path(__file__).resolve().parents[2] / "cache" / "local_voice"
DEFAULT_VOICE = "/home/shadowfax/jarvis/voices/en_GB-alan-medium.onnx"
DEFAULT_PIPER = "/home/shadowfax/jarvis/.venv-voice/bin/piper"

# Only these fixed phrases are cached. Unrecognized/dynamic text uses Piper.
LOCAL_REPLIES = frozenset({
    BOOT_GREETING,
    *(pair[0] for pair in PROMPTS.values()),
    "Motors armed.",
    "Motors disarmed.",
    "I couldn't arm the motors. Check the drive service.",
    "Motor disarm failed. Use the physical power switch.",
    "Rebooting Jarvis.",
    "Powering down Jarvis.",
    "Power command failed.",
})


def cache_dir():
    return Path(os.environ.get("JARVIS_LOCAL_AUDIO_CACHE", str(DEFAULT_CACHE)))


def cache_file(text):
    if text not in LOCAL_REPLIES:
        return None
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return cache_dir() / (digest + ".wav")


def valid_wav(path):
    try:
        if not path.is_file() or path.stat().st_size < 100:
            return False
        with wave.open(str(path), "rb") as wav:
            return wav.getnframes() > 0 and wav.getnchannels() >= 1
    except (OSError, EOFError, wave.Error):
        return False


def generate():
    voice = os.environ.get("JARVIS_PIPER_VOICE", DEFAULT_VOICE)
    binary = os.environ.get("JARVIS_PIPER_BIN", DEFAULT_PIPER)
    if not Path(voice).is_file() or not Path(voice + ".json").is_file():
        raise FileNotFoundError("Piper voice model/config missing: " + voice)
    if not Path(binary).is_file():
        raise FileNotFoundError("Piper binary missing: " + binary)
    cache_dir().mkdir(parents=True, exist_ok=True)
    for text in sorted(LOCAL_REPLIES):
        path = cache_file(text)
        temp = path.with_suffix(".tmp.wav")
        try:
            result = subprocess.run(
                [binary, "--model", voice, "--output_file", str(temp)],
                input=text + "\n", text=True, capture_output=True, timeout=120,
                check=False,
            )
            if result.returncode != 0 or not valid_wav(temp):
                raise RuntimeError(
                    f"Piper failed for {text!r}: {result.stderr[-500:]}"
                )
            temp.replace(path)  # atomic replacement on the same filesystem
            print(f"[LOCAL AUDIO] Cached {text!r}: {path}", flush=True)
        finally:
            temp.unlink(missing_ok=True)


async def play_local_response(text, *, device, fallback):
    """Play a cached response; fall back to existing async Piper playback."""
    path = cache_file(text)
    if path is not None and valid_wav(path):
        player = await asyncio.create_subprocess_exec(
            "aplay", "-q", "-D", device, str(path)
        )
        if await player.wait() == 0:
            print(f"[LOCAL AUDIO] Cache hit: {text!r}", flush=True)
            return
        print(f"[LOCAL AUDIO] Cached playback failed: {text!r}", flush=True)
    else:
        print(f"[LOCAL AUDIO] Cache miss: {text!r}", flush=True)
    await fallback(text)


if __name__ == "__main__":
    if sys.argv[1:] != ["generate"]:
        raise SystemExit("Usage: python clients/voice/local_audio.py generate")
    generate()
