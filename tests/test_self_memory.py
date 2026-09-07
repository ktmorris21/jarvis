from jarvis_core.memory import memory
from jarvis_core.persistence import init_db
from jarvis_core.persistence.repository import repository


def test_self_defining_speech_forms_episodic_memory():
    init_db()
    before = len(repository.memories(10000))
    event_id = repository.record_event(
        event_type="JARVIS_SPOKE",
        source="jarvis:core",
        occurred_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        data={
            "ability": "speaker",
            "command_id": "cmd-test-color",
            "data": {"text": "I choose electric blue as my favorite color."},
        },
    )
    created = memory.form_from_event(
        event_type="JARVIS_SPOKE",
        source="jarvis:core",
        data={
            "ability": "speaker",
            "command_id": "cmd-test-color",
            "data": {"text": "I choose electric blue as my favorite color."},
        },
        source_event_id=event_id,
        context={},
    )
    assert len(created) == 1
    after = repository.memories(10000)
    assert len(after) == before + 1
    assert any("electric blue" in m["content"].lower() for m in after)


def test_routine_jarvis_speech_does_not_form_memory():
    init_db()
    event_id = repository.record_event(
        event_type="JARVIS_SPOKE",
        source="jarvis:core",
        occurred_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        data={
            "ability": "speaker",
            "command_id": "cmd-test-routine",
            "data": {"text": "The time is seven thirty."},
        },
    )
    created = memory.form_from_event(
        event_type="JARVIS_SPOKE",
        source="jarvis:core",
        data={
            "ability": "speaker",
            "command_id": "cmd-test-routine",
            "data": {"text": "The time is seven thirty."},
        },
        source_event_id=event_id,
        context={},
    )
    assert created == []


def test_self_memory_retrieval_finds_favorite_color():
    init_db()
    mid = memory.remember_semantic(
        "Jarvis prefers electric blue.",
        tags=["jarvis", "self", "favorite", "color", "electric", "blue"],
        salience=0.9,
        source="test",
    )
    found = memory.retrieve("Jarvis favorite color", limit=5)
    assert any(m["id"] == mid for m in found)
