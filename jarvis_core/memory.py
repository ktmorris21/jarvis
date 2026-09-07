from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from .persistence.repository import repository


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _tokens(text: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-z0-9']+", text.lower())
        if len(t) > 2 and t not in {
            "the", "and", "for", "with", "that", "this", "was", "are", "you",
            "your", "has", "had", "from", "but", "not", "into", "about", "user",
        }
    }


class MemoryService:
    """Phase 2 memory formation + retrieval.

    Memory is durable knowledge Jarvis chooses to retain. Events remain the immutable
    source history; this service creates concise retained representations from selected
    events and retrieves only a small relevant subset for cognition.
    """

    def form_from_event(
        self,
        *,
        event_type: str,
        source: str,
        data: dict[str, Any],
        source_event_id: str,
        context: dict[str, Any] | None = None,
    ) -> list[str]:
        context = context or {}
        created: list[str] = []

        # A return is meaningful only on an actual absent -> present transition.
        if event_type == "USER_ACTIVE" and context.get("was_present") is False:
            created.append(repository.add_memory(
                memory_type="episodic",
                content=f"The user returned and became active through {source}.",
                data={
                    "source_event_id": source_event_id,
                    "source": source,
                    "tags": ["user", "return", "presence", source],
                    "formation": "deterministic_event_rule",
                },
                salience=0.55,
            ))

        elif event_type == "USER_IDLE" and context.get("was_present") is True:
            created.append(repository.add_memory(
                memory_type="episodic",
                content=f"The user became idle or absent from {source}.",
                data={
                    "source_event_id": source_event_id,
                    "source": source,
                    "tags": ["user", "idle", "absence", source],
                    "formation": "deterministic_event_rule",
                },
                salience=0.35,
            ))

        elif event_type == "USER_SPOKE":
            text = str(data.get("text", "")).strip()
            if text:
                # This is an episode (what was said), not automatically a semantic fact.
                # Semantic promotion will be a separate, stricter operation later.
                clipped = text[:1000]
                created.append(repository.add_memory(
                    memory_type="episodic",
                    content=f'User said: "{clipped}"',
                    data={
                        "source_event_id": source_event_id,
                        "source": source,
                        "tags": ["user", "speech", "conversation", source],
                        "formation": "deterministic_event_rule",
                    },
                    salience=0.65,
                ))

        elif event_type == "COMMAND_RESULT" and data.get("status") == "failed":
            ability = data.get("ability") or "unknown ability"
            created.append(repository.add_memory(
                memory_type="episodic",
                content=f"A Jarvis body/interface command failed while attempting {ability}.",
                data={
                    "source_event_id": source_event_id,
                    "source": source,
                    "tags": ["failure", "command", str(ability), source],
                    "formation": "deterministic_event_rule",
                    "result": data,
                },
                salience=0.75,
            ))

        return created

    def retrieve(self, query: str, *, limit: int = 5, memory_type: str | None = None) -> list[dict]:
        candidates = repository.memories(limit=250, memory_type=memory_type)
        qtokens = _tokens(query)
        now = utc_now()
        scored: list[tuple[float, dict]] = []

        for memory in candidates:
            mtokens = _tokens(memory["content"] + " " + " ".join(memory.get("data", {}).get("tags", [])))
            overlap = len(qtokens & mtokens) / max(1, len(qtokens))
            salience = float(memory.get("salience", 0.5))
            created_at = datetime.fromisoformat(memory["created_at"])
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            age_days = max(0.0, (now - created_at).total_seconds() / 86400.0)
            recency = math.exp(-age_days / 30.0)

            # Keyword relevance dominates, but salient/recent memories can still surface.
            score = overlap * 0.70 + salience * 0.20 + recency * 0.10
            if overlap > 0 or salience >= 0.70:
                memory = dict(memory)
                memory["relevance_score"] = round(score, 4)
                scored.append((score, memory))

        scored.sort(key=lambda x: (x[0], x[1]["created_at"]), reverse=True)
        selected = [m for _, m in scored[: max(1, min(limit, 20))]]
        if selected:
            repository.note_memories_retrieved([m["id"] for m in selected])
        return selected

    def remember_semantic(self, content: str, *, tags: list[str] | None = None, salience: float = 0.7, source: str = "manual") -> str:
        return repository.add_memory(
            memory_type="semantic",
            content=content.strip(),
            data={
                "tags": tags or [],
                "formation": "explicit_semantic_memory",
                "source": source,
            },
            salience=max(0.0, min(float(salience), 1.0)),
        )


memory = MemoryService()
