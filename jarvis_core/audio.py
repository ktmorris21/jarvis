"""Speech transcription on Core. TTS synthesis is local to the Pi via Piper."""
import base64
import io
import re
import wave
import httpx
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

    async def synthesize_wav_base64(self, text: str) -> str:
        """Remote synthesis to PCM, packaged in a WAV container for Pi playback."""
        if not settings.elevenlabs_api_key:
            raise RuntimeError("ElevenLabs API key not configured")
        spoken = re.sub(r"\\*\\*(.*?)\\*\\*", r"\\1", text)
        spoken = re.sub(r"(?m)^\\s{0,3}#{1,6}\\s+", "", spoken)
        spoken = re.sub(r"(?m)^\\s*[-*]\\s+", "", spoken)
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=50) as client:
            response = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}",
                params={"output_format": "pcm_16000"},
                headers={"xi-api-key": settings.elevenlabs_api_key,
                         "Content-Type": "application/json", "Accept": "audio/pcm"},
                json={"text": spoken.strip(), "model_id": settings.elevenlabs_model},
            )
            response.raise_for_status()
        if not response.content or len(response.content) % 2:
            raise RuntimeError("ElevenLabs returned invalid PCM audio")
        out = io.BytesIO()
        with wave.open(out, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(response.content)
        logger.info("[AUDIO TIMING] ElevenLabs full synthesis %.2fs",
                    time.perf_counter() - start)
        return base64.b64encode(out.getvalue()).decode("ascii")


audio = AudioService()
