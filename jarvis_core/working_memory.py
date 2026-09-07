from __future__ import annotations

from datetime import datetime, timezone

from .config import settings
from .persistence.repository import repository


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkingMemory:
    """Short-lived verbatim conversation context.

    This is intentionally not long-term memory. It exists so references like
    "pick one" resolve against the conversation that is still in progress.
    """

    ENTITY_ID = "conversation:primary"

    def _load(self) -> dict:
        return repository.get_state(self.ENTITY_ID) or {"turns": []}

    def turns(self) -> list[dict]:
        return list(self._load().get("turns", []))

    def add_turn(self, role: str, content: str, source: str) -> list[dict]:
        content = (content or "").strip()
        if not content:
            return self.turns()

        now = utc_now()
        state = self._load()
        turns = list(state.get("turns", []))

        # A long silence ends the active conversation. Durable memories/events
        # remain elsewhere; verbatim working context starts fresh.
        if turns:
            try:
                last = datetime.fromisoformat(turns[-1]["timestamp"])
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                gap = (now - last).total_seconds()
                if gap > settings.working_memory_timeout_seconds:
                    turns = []
            except Exception:
                turns = []

        turns.append({
            "role": role,
            "content": content[: settings.working_memory_turn_char_limit],
            "source": source,
            "timestamp": now.isoformat(),
        })
        turns = turns[-settings.working_memory_turns :]
        repository.upsert_state(
            self.ENTITY_ID,
            "working_memory",
            {"turns": turns, "updated_at": now.isoformat()},
        )
        return turns

    def clear(self) -> None:
        repository.upsert_state(
            self.ENTITY_ID,
            "working_memory",
            {"turns": [], "updated_at": utc_now().isoformat()},
        )


working_memory = WorkingMemory()
