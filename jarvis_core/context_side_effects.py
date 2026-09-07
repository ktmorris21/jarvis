from __future__ import annotations

from .config import settings
from .memory import memory
from .persistence.repository import repository


class ContextSideEffects:
    """Integrity gate for LLM-proposed durable changes.

    Core does not try to understand the semantics. It enforces bounded counts,
    confidence thresholds, exact dedupe, and persistence shape.
    """

    def apply(self, turn, source: str) -> dict:
        accepted_memories = []
        accepted_goals = []
        rejected = []

        for proposal in turn.memory_proposals[:2]:
            if proposal.confidence < settings.context_memory_accept_confidence:
                rejected.append({"type": "memory", "reason": "confidence", "content": proposal.content})
                continue
            if repository.memory_exists_exact(proposal.content):
                rejected.append({"type": "memory", "reason": "duplicate", "content": proposal.content})
                continue
            mid = memory.remember_semantic(
                proposal.content,
                tags=proposal.tags,
                salience=proposal.salience,
                source=f"cognition:{source}",
            )
            accepted_memories.append(mid)

        for proposal in turn.goal_proposals[:1]:
            if proposal.confidence < settings.context_goal_accept_confidence:
                rejected.append({"type": "goal", "reason": "confidence", "description": proposal.description})
                continue
            gid = repository.create_goal(
                proposal.kind,
                proposal.description,
                proposal.priority,
                {
                    "event_subscriptions": proposal.event_subscriptions,
                    "created_by": "cognition_proposal",
                    "source": source,
                    "proposal_reason": proposal.reason,
                },
            )
            accepted_goals.append(gid)

        return {
            "accepted_memory_ids": accepted_memories,
            "accepted_goal_ids": accepted_goals,
            "rejected": rejected,
        }


context_side_effects = ContextSideEffects()
