"""Checks for deterministic local voice reply cache lookup."""
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "voice"))

from local_audio import LOCAL_REPLIES, cache_file, valid_wav
from local_commands import PROMPTS
from boot_notice import BOOT_GREETING


def test_prompts_and_outcomes_all_have_cache_entries():
    for prompt, _ in PROMPTS.values():
        assert prompt in LOCAL_REPLIES
        assert cache_file(prompt) is not None
    for reply in ("Motors armed.", "Motors disarmed.", "Powering down Jarvis.", BOOT_GREETING):
        assert cache_file(reply) is not None


def test_unknown_reply_never_treated_as_cached():
    assert cache_file("Long Agent response") is None


def test_cache_filename_deterministic():
    assert cache_file("Motors armed.") == cache_file("Motors armed.")
    assert cache_file("Motors armed.") != cache_file("Motors disarmed.")


def test_wav_validation(tmp_path):
    missing = tmp_path / "missing.wav"
    assert not valid_wav(missing)
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not a wav")
    assert not valid_wav(bad)
    good = tmp_path / "good.wav"
    with wave.open(str(good), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\x00\x00" * 200)
    assert valid_wav(good)
