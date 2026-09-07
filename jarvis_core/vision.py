from __future__ import annotations

import base64
import json
from typing import Any

from pydantic import BaseModel, Field

from .config import settings


class VisionObservation(BaseModel):
    summary: str = Field(min_length=1, max_length=500)
    notable: list[str] = Field(default_factory=list, max_length=8)
    people_visible: bool = False
    person_count_estimate: int | None = Field(default=None, ge=0, le=20)
    scene_changed: bool | None = None
    attention_hint: str = Field(
        default="routine",
        pattern="^(routine|interesting|important)$",
    )


VISION_INSTRUCTIONS = """You are Jarvis Core's visual perception service.
Interpret only what is visible in the supplied image.

Return a compact structured observation for another system to reason over.
Do not invent identities, names, intentions, locations, or events that aren't visually supported.
Prefer concrete descriptions over speculation.
The attention_hint is only a hint:
- routine: ordinary scene, nothing requiring special attention
- interesting: a person/object/change may merit executive attention
- important: visually obvious urgent hazard or exceptional condition

Keep summary concise. notable should contain only a few concrete visible facts.
"""


class VisionService:
    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        return self._client

    async def observe_jpeg(self, jpeg_bytes: bytes) -> VisionObservation:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for vision")

        encoded = base64.b64encode(jpeg_bytes).decode("ascii")
        response = await self._get_client().responses.parse(
            model=settings.vision_model,
            instructions=VISION_INSTRUCTIONS,
            input=[{
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Describe the current visual scene for Jarvis.",
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:image/jpeg;base64,{encoded}",
                    },
                ],
            }],
            text_format=VisionObservation,
        )
        obs = response.output_parsed
        if obs is None:
            raise RuntimeError("Vision model returned no parsed observation")
        return obs


vision = VisionService()
