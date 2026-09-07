import base64
from io import BytesIO

from .config import settings


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
        result = await self._get_client().audio.transcriptions.create(
            model=settings.stt_model,
            file=("utterance.wav", wav_bytes, "audio/wav"),
        )
        return (result.text or "").strip()

    async def synthesize_wav_base64(self, text: str) -> str:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for speech synthesis")
        response = await self._get_client().audio.speech.create(
            model=settings.tts_model,
            voice=settings.tts_voice,
            input=text,
            response_format="wav",
        )
        return base64.b64encode(response.content).decode("ascii")


audio = AudioService()
