"""Speech transcription on Core. TTS synthesis is local to the Pi via Piper."""
import logging
import time

from .config import settings

logger = logging.getLogger(__name__)
TRANSCRIPTION_CONTEXT = (
    "This conversation is with Jarvis, an autonomous Raspberry Pi robot "
    "using a SunFounder PiCar-X. Vocabulary: LiDAR, RPLIDAR, ROS 2, SLAM, "
    "slam_toolbox, Nav2, mapping, localization, telemetry, Raspberry Pi."
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


audio = AudioService()
