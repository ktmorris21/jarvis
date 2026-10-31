"""Core chained voice configuration smoke tests."""
from jarvis_core.config import settings


def test_core_uses_supported_transcription_model():
    assert settings.stt_model == "gpt-transcribe"


def test_core_does_not_require_cloud_tts_configuration():
    assert not hasattr(settings, "elevenlabs_api_key")
