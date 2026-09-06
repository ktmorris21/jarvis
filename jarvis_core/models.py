from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InterfaceEvent(BaseModel):
    type: str = "event"
    event: str
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utc_now)


class InterfaceHello(BaseModel):
    type: str = "hello"
    interface_id: str
    interface_type: str = "generic"
    capabilities: list[str] = Field(default_factory=list)


class Command(BaseModel):
    type: str = "command"
    command_id: str = Field(default_factory=lambda: uuid4().hex)
    ability: str
    target: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utc_now)


class DebugCommandRequest(BaseModel):
    target: str
    ability: str
    data: dict[str, Any] = Field(default_factory=dict)
