import base64
import logging
import time

from .config import settings

logger = logging.getLogger(__name__)

TRANSCRIPTION_CONTEXT = (
    "This conversation is with Jarvis, an autonomous "
    "Raspberry Pi robot using a SunFounder PiCar-X. "
    "Common technical vocabulary: LiDAR, RPLIDAR C1, "
    "ROS 2, SLAM, slam_toolbox, Nav2, mapping, "
    "localization, telemetry, Raspberry Pi, and PiCar-X. "
    "Transcribe these technical terms accurately when spoken."
)


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
            raise RuntimeError("OPENAI_API_KEY is required for speech transcription")
        start = time.perf_counter()
        try:
            result = await self._get_client().audio.transcriptions.create(
                model=settings.stt_model,
                file=("utterance.wav", wav_bytes, "audio/wav"),
                prompt=TRANSCRIPTION_CONTEXT,
            )
            return (result.text or "").strip()
        finally:
            logger.warning(
                "[AUDIO TIMING] STT completed in %.2fs",
                time.perf_counter() - start,
            )

    async def synthesize_wav_base64(self, text: str) -> str:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for speech synthesis")
        start = time.perf_counter()
        try:
            response = await self._get_client().audio.speech.create(
                model=settings.tts_model,
                voice=settings.tts_voice,
                input=text,
                response_format="wav",
            )
            return base64.b64encode(response.content).decode("ascii")
        finally:
            logger.warning(
                "[AUDIO TIMING] TTS completed in %.2fs",
                time.perf_counter() - start,
            )


audio = AudioService()
