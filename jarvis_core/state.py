import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import WebSocket

from .config import settings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class InterfaceConnection:
    interface_id: str
    interface_type: str
    capabilities: list[str]
    websocket: WebSocket
    connected_at: datetime = field(default_factory=utc_now)


class JarvisState:
    """POC state only. This becomes repository-backed state later."""

    def __init__(self) -> None:
        self.started_at = utc_now()
        self.interfaces: dict[str, InterfaceConnection] = {}
        self.user_present = False
        self.last_user_activity: datetime | None = None
        self.last_interaction: datetime | None = None
        self.social_drive = 0.10
        self.boredom = 0.00
        self.event_count = 0
        self.recent_events: list[str] = []
        self.last_cognition_action: str | None = None
        self.last_cognition_reason: str | None = None
        self.last_cognition_at: datetime | None = None
        self._lock = asyncio.Lock()

    async def register(self, connection: InterfaceConnection) -> None:
        async with self._lock:
            self.interfaces[connection.interface_id] = connection

    async def unregister(self, interface_id: str) -> None:
        async with self._lock:
            self.interfaces.pop(interface_id, None)

    def remember_event(self, event: str) -> None:
        self.recent_events.append(event)
        if len(self.recent_events) > 20:
            del self.recent_events[:-20]

    async def snapshot(self) -> dict:
        async with self._lock:
            return {
                "started_at": self.started_at.isoformat(),
                "interfaces": [
                    {
                        "interface_id": c.interface_id,
                        "interface_type": c.interface_type,
                        "capabilities": c.capabilities,
                        "connected_at": c.connected_at.isoformat(),
                    }
                    for c in self.interfaces.values()
                ],
                "user_present": self.user_present,
                "last_user_activity": self.last_user_activity.isoformat() if self.last_user_activity else None,
                "last_interaction": self.last_interaction.isoformat() if self.last_interaction else None,
                "social_drive": round(self.social_drive, 3),
                "boredom": round(self.boredom, 3),
                "event_count": self.event_count,
                "recent_events": self.recent_events[-8:],
                "cognition": {
                    "enabled": bool(settings.openai_api_key),
                    "last_action": self.last_cognition_action,
                    "last_reason": self.last_cognition_reason,
                    "last_at": self.last_cognition_at.isoformat() if self.last_cognition_at else None,
                },
            }


state = JarvisState()
