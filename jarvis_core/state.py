import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import WebSocket

from .config import settings
from .persistence.repository import repository


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
    """Live operational state. Durable beliefs/history are mirrored to the repository."""
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
        self.last_command_result: dict | None = None
        self._lock = asyncio.Lock()

    def restore(self) -> None:
        user = repository.get_state("person:user") or {}
        jarvis = repository.get_state("jarvis:core") or {}
        self.user_present = bool(user.get("present", False))
        self.social_drive = float(jarvis.get("social_drive", 0.10))
        self.boredom = float(jarvis.get("boredom", 0.00))
        self.recent_events = [x["type"] for x in repository.recent_events(20)]
        self.event_count = len(repository.recent_events(1000))

    def persist_runtime(self) -> None:
        repository.upsert_state("person:user", "person", {
            "present": self.user_present,
            "last_user_activity": self.last_user_activity.isoformat() if self.last_user_activity else None,
            "last_interaction": self.last_interaction.isoformat() if self.last_interaction else None,
        })
        repository.upsert_state("jarvis:core", "jarvis", {
            "social_drive": round(self.social_drive, 4),
            "boredom": round(self.boredom, 4),
            "last_cognition_action": self.last_cognition_action,
            "last_cognition_reason": self.last_cognition_reason,
        })

    async def register(self, connection: InterfaceConnection) -> None:
        async with self._lock:
            self.interfaces[connection.interface_id] = connection
        repository.note_interface(connection.interface_id, connection.interface_type, connection.capabilities)

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
                "live_interfaces": [{"interface_id": c.interface_id,"interface_type": c.interface_type,"capabilities": c.capabilities,"connected_at": c.connected_at.isoformat()} for c in self.interfaces.values()],
                "known_interfaces": repository.interfaces(),
                "world_state": repository.all_states(),
                "user_present": self.user_present,
                "social_drive": round(self.social_drive, 3),
                "boredom": round(self.boredom, 3),
                "event_count": self.event_count,
                "recent_events": repository.recent_events(8),
                "active_goals": repository.goals("active"),
                "recent_actions": repository.recent_actions(8),
                "last_command_result": self.last_command_result,
                "cognition": {"enabled": bool(settings.openai_api_key),"last_action": self.last_cognition_action,"last_reason": self.last_cognition_reason,"last_at": self.last_cognition_at.isoformat() if self.last_cognition_at else None},
            }


state = JarvisState()
