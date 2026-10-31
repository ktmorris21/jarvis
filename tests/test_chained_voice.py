"""Piper voice helper tests; no model download or audio hardware needed."""
import asyncio

import pytest

from clients.voice.voice_interface import play_piper


def test_piper_requires_nonempty_text():
    with pytest.raises(ValueError, match="Empty TTS"):
        asyncio.run(play_piper(" "))


def test_piper_missing_voice_fails_closed(monkeypatch):
    monkeypatch.setenv("JARVIS_PIPER_VOICE", "/definitely/missing/voice.onnx")
    with pytest.raises(FileNotFoundError, match="Piper voice"):
        asyncio.run(play_piper("Hello"))
