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


class MemoryCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    memory_type: str = "semantic"
    tags: list[str] = Field(default_factory=list)
    salience: float = Field(default=0.7, ge=0.0, le=1.0)


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=5, ge=1, le=20)
    memory_type: str | None = None
