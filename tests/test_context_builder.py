from types import SimpleNamespace

from jarvis_core.context_builder import context_builder
from jarvis_core.context_side_effects import context_side_effects
from jarvis_core.memory import memory
from jarvis_core.persistence import init_db
from jarvis_core.persistence.repository import repository
from jarvis_core.working_memory import working_memory


def test_working_memory_preserves_verbatim_recent_turns():
    init_db()
    working_memory.clear()
    working_memory.add_turn("user", "Pick a favorite color.", "picar-main")
    working_memory.add_turn("assistant", "Electric blue.", "jarvis:core")
    working_memory.add_turn("user", "Why that one?", "picar-main")
    turns = working_memory.turns()
    assert [t["content"] for t in turns[-3:]] == [
        "Pick a favorite color.",
        "Electric blue.",
        "Why that one?",
    ]


def test_context_gather_includes_working_memory_goal_and_candidates():
    init_db()
    working_memory.clear()
    working_memory.add_turn("user", "Pick a favorite animal.", "picar-main")
    working_memory.add_turn("assistant", "Otter.", "jarvis:core")
    mid = memory.remember_semantic(
        "Jarvis's favorite animal is an otter.",
        tags=["jarvis", "favorite", "animal", "otter"],
        salience=0.9,
        source="test",
    )
    gid = repository.create_goal(
        "count_barks",
        "Count dog barks for five minutes.",
        80,
        {"event_subscriptions": ["DOG_BARK"]},
    )
    draft = context_builder.gather("Why did you pick that one?", "picar-main")
    assert any(t["content"] == "Otter." for t in draft.working_turns)
    assert any(g["id"] == gid for g in draft.active_goals)
    assert any(m["id"] == mid for m in draft.candidate_memories)
    assert len(draft.candidate_memories) <= 12


def test_core_accepts_high_confidence_memory_proposal_and_rejects_low_confidence_goal():
    init_db()
    content = "Jarvis's favorite color is electric blue."
    turn = SimpleNamespace(
        memory_proposals=[SimpleNamespace(
            content=content,
            tags=["jarvis", "favorite", "color"],
            salience=0.9,
            confidence=0.95,
            reason="Jarvis made a stable self-choice.",
        )],
        goal_proposals=[SimpleNamespace(
            kind="wander",
            description="Wander around aimlessly.",
            priority=50,
            event_subscriptions=[],
            confidence=0.2,
            reason="Not actually requested.",
        )],
    )
    result = context_side_effects.apply(turn, "picar-main")
    assert len(result["accepted_memory_ids"]) == 1
    assert result["accepted_goal_ids"] == []
    assert any(r["type"] == "goal" and r["reason"] == "confidence" for r in result["rejected"])
    assert repository.memory_exists_exact(content)
