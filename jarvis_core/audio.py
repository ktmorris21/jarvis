"""Speech transcription and optional ElevenLabs synthesized speech on Core."""
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
        """Request a real WAV and validate it before sending to the Pi."""
        if not settings.elevenlabs_api_key:
            raise RuntimeError("ElevenLabs API key not configured")
        spoken = re.sub(r"\\*\\*(.*?)\\*\\*", r"\\1", text)
        spoken = re.sub(r"(?m)^\\s{0,3}#{1,6}\\s+", "", spoken)
        spoken = re.sub(r"(?m)^\\s*[-*]\\s+", "", spoken).strip()
        if not spoken:
            raise ValueError("Empty TTS text")
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=50) as client:
            response = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}",
                params={"output_format": "wav_16000"},
                headers={"xi-api-key": settings.elevenlabs_api_key,
                         "Content-Type": "application/json", "Accept": "audio/wav"},
                json={"text": spoken, "model_id": settings.elevenlabs_model},
            )
            response.raise_for_status()
        data = response.content
        try:
            with wave.open(io.BytesIO(data), "rb") as wav:
                rate = wav.getframerate()
                channels = wav.getnchannels()
                width = wav.getsampwidth()
                seconds = wav.getnframes() / rate
        except (wave.Error, EOFError, ValueError, ZeroDivisionError) as exc:
            raise RuntimeError(
                "ElevenLabs response is not a valid WAV "
                f"(content-type={response.headers.get('content-type')}, "
                f"bytes={len(data)}, magic={data[:12].hex()})"
            ) from exc
        logger.info(
            "[AUDIO TIMING] ElevenLabs synthesis %.2fs; "
            "WAV %.2fs, %dHz, %dch, %dbit, %d bytes",
            time.perf_counter() - start, seconds, rate, channels, width * 8, len(data))
        if rate != 16000 or channels != 1 or width != 2:
            raise RuntimeError(
                f"Unexpected ElevenLabs audio format: {rate}Hz, {channels}ch, {width * 8}bit"
            )
        if not 0.1 <= seconds <= 30:
            raise RuntimeError(f"Suspicious ElevenLabs audio duration: {seconds:.1f}s")
        return base64.b64encode(data).decode("ascii")


audio = AudioService()
