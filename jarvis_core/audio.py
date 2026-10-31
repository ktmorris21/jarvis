"""Provider-independent audio boundary for the chained Agents SDK voice path.

STT: OpenAI gpt-transcribe (current supported model).
TTS: ElevenLabs Flash, returning 16 kHz PCM wrapped as WAV for the existing
Pi voice client's audio_wav_base64 speaker protocol.
"""
import base64
import io
import logging
import time
import wave

import httpx

from .config import settings

logger = logging.getLogger(__name__)

TRANSCRIPTION_CONTEXT = (
    "This conversation is with Jarvis, an autonomous "
    "Raspberry Pi robot using a SunFounder PiCar-X. "
    "Common technical vocabulary: LiDAR, RPLIDAR, "
    "ROS 2, SLAM, slam_toolbox, Nav2, mapping, "
    "localization, telemetry, Raspberry Pi, and PiCar-X."
)


def pcm16_to_wav(pcm: bytes, *, rate: int = 16000) -> bytes:
    """Wrap signed 16-bit mono PCM in a standard WAV container."""
    if not pcm or len(pcm) % 2:
        raise ValueError("Invalid or empty PCM response from TTS provider")
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return out.getvalue()


class AudioService:
    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        return self._client

    async def transcribe_wav(self, wav_bytes: bytes) -> str:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for transcription")
        start = time.perf_counter()
        try:
            result = await self._get_client().audio.transcriptions.create(
                model=settings.stt_model,
                file=("utterance.wav", wav_bytes, "audio/wav"),
                prompt=TRANSCRIPTION_CONTEXT,
            )
            return (result.text or "").strip()
        finally:
            logger.info("[AUDIO TIMING] STT %.2fs", time.perf_counter() - start)

    async def synthesize_wav_base64(self, text: str) -> str:
        """Generate speech from the Agent SDK's exact text, without a second LLM."""
        if not settings.elevenlabs_api_key or not settings.tts_voice:
            raise RuntimeError(
                "ElevenLabs TTS requires JARVIS_ELEVENLABS_API_KEY "
                "(or ELEVENLABS_API_KEY) and JARVIS_TTS_VOICE"
            )
        start = time.perf_counter()
        try:
            # The PCM format avoids a transcoding dependency on Railway.
            # The existing Pi client expects a WAV payload.
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(
                    "https://api.elevenlabs.io/v1/text-to-speech/"
                    + settings.tts_voice,
                    params={"output_format": "pcm_16000"},
                    headers={
                        "xi-api-key": settings.elevenlabs_api_key,
                        "Content-Type": "application/json",
                        "Accept": "audio/pcm",
                    },
                    json={"text": text, "model_id": settings.tts_model},
                )
                response.raise_for_status()
            return base64.b64encode(pcm16_to_wav(response.content)).decode("ascii")
        finally:
            logger.info("[AUDIO TIMING] TTS %.2fs", time.perf_counter() - start)


audio = AudioService()
