"""Core chained voice configuration smoke tests."""
from jarvis_core.config import settings


def test_core_uses_supported_transcription_model():
    assert settings.stt_model == "gpt-transcribe"


def test_core_does_not_require_cloud_tts_configuration():
    assert not hasattr(settings, "elevenlabs_api_key")


def test_markdown_cleanup_preserves_spoken_words():
    from jarvis_core.audio import clean_speech_text
    answer = ("LiDAR is **active and healthy**. The latest scan is "
              "**0.096 seconds old**, and mapping is updating normally.")
    assert clean_speech_text(answer) == (
        "LiDAR is active and healthy. The latest scan is "
        "0.096 seconds old, and mapping is updating normally."
    )
    assert "\\1" not in clean_speech_text(answer)
