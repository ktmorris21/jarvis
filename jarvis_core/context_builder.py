from __future__ import annotations

from dataclasses import dataclass

from .config import settings
from .memory import memory
from .persistence.repository import repository
from .working_memory import working_memory


IDENTITY = """You are Jarvis, one persistent agent whose Core is the continuing self.
Desktop, PiCar, phone, speakers, and future devices are interfaces or bodies available to you; they are not separate Jarvis instances.
You may form stable preferences, tastes, opinions, and choices. When context shows that you previously chose or preferred something, treat that as your own continuing preference unless later evidence changes it.
Do not fall back to generic 'I am only an AI and do not really have preferences' disclaimers unless the distinction is genuinely relevant.
Be conversationally natural, concise by default, and consistent with current goals, world state, working conversation, and durable memory.
Never invent a memory merely because one would make the conversation smoother."""


@dataclass
class ContextDraft:
    source: str
    current_text: str
    identity: str
    working_turns: list[dict]
    active_goals: list[dict]
    world_state: list[dict]
    candidate_memories: list[dict]


@dataclass
class ContextPacket:
    source: str
    current_text: str
    identity: str
    working_turns: list[dict]
    active_goals: list[dict]
    world_state: list[dict]
    selected_memories: list[dict]
    selection_reason: str


class ContextBuilder:
    def gather(self, current_text: str, source: str) -> ContextDraft:
        # Working memory is always verbatim and requires no retrieval judgment.
        turns = working_memory.turns()

        # Active goals are bounded because only a small number should matter at once.
        goals = repository.goals("active")[: settings.context_goal_limit]

        # World state is bounded and prioritizes the user, Jarvis, and observations
        # related to active goals. This is not a dump of the entire database.
        all_states = repository.all_states()
        goal_ids = {g["id"] for g in goals}
        world = []
        for item in all_states:
            eid = item.get("entity_id", "")
            if eid in {"person:user", "jarvis:core"}:
                world.append(item)
            elif eid.startswith("task_observation:") and eid.split(":", 1)[1] in goal_ids:
                world.append(item)
            if len(world) >= settings.context_world_state_limit:
                break

        # Cheap lexical/salience retrieval produces candidates only. The selector
        # LLM decides which of these actually enter active cognition context.
        query_parts = [current_text]
        query_parts.extend(t.get("content", "") for t in turns[-4:])
        query = " ".join(query_parts)
        candidates = memory.candidates(query, limit=settings.context_memory_candidates)

        return ContextDraft(
            source=source,
            current_text=current_text,
            identity=IDENTITY,
            working_turns=turns,
            active_goals=goals,
            world_state=world,
            candidate_memories=candidates,
        )

    def finalize(self, draft: ContextDraft, selected_ids: list[str], reason: str) -> ContextPacket:
        allowed = {m["id"]: m for m in draft.candidate_memories}
        selected = []
        for mid in selected_ids[: settings.context_selected_memory_limit]:
            if mid in allowed and mid not in {m["id"] for m in selected}:
                selected.append(allowed[mid])
        if selected:
            repository.note_memories_retrieved([m["id"] for m in selected])
        return ContextPacket(
            source=draft.source,
            current_text=draft.current_text,
            identity=draft.identity,
            working_turns=draft.working_turns,
            active_goals=draft.active_goals,
            world_state=draft.world_state,
            selected_memories=selected,
            selection_reason=reason,
        )


context_builder = ContextBuilder()
