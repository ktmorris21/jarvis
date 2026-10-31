"""Unit coverage for the independent chained-voice codec boundary."""
import base64
import io
import wave

import pytest

from jarvis_core.audio import pcm16_to_wav, AudioService
from jarvis_core.config import settings


def test_pcm16_wraps_as_mono_16khz_wav():
    raw = b"\x00\x00\xff\x7f\x00\x80"
    encoded = pcm16_to_wav(raw)
    with wave.open(io.BytesIO(encoded), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        assert wf.readframes(3) == raw


def test_pcm16_rejects_empty_or_misaligned_response():
    with pytest.raises(ValueError):
        pcm16_to_wav(b"")
    with pytest.raises(ValueError):
        pcm16_to_wav(b"\x00")


@pytest.mark.asyncio
async def test_tts_refuses_missing_credentials(monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", None)
    monkeypatch.setattr(settings, "tts_voice", "")
    with pytest.raises(RuntimeError, match="ElevenLabs TTS requires"):
        await AudioService().synthesize_wav_base64("Hello")
