"""Regression checks for a single Core tool registry and transcript stream."""
import asyncio
from jarvis_core.abilities import CORE_TOOLS, execute_tool, tool_schemas


def test_registry_exports_all_core_tools():
    names = {entry["name"] for entry in tool_schemas()}
    assert names == set(CORE_TOOLS)
    assert {"get_robot_status", "search_memories", "inspect_environment",
            "turtle_status"} <= names


def test_shared_memory_dispatch(monkeypatch):
    from jarvis_core import agent_runtime

    monkeypatch.setattr(agent_runtime, "search_memory_data",
                        lambda q: [{"content": "remembered " + q}])
    result = asyncio.run(execute_tool("search_memories", {"query": "dogs"}))
    assert result["memories"][0]["content"] == "remembered dogs"


def test_camera_does_not_pretend_to_capture_from_desktop():
    result = asyncio.run(execute_tool("inspect_environment",
                                      {"question": "What do you see?"}))
    assert result["available"] is False
    assert "camera" in result["reason"].lower()


def test_desktop_turns_enter_canonical_conversation_stream(monkeypatch):
    from jarvis_core import executive, agent_runtime
    from jarvis_core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    saved = []
    monkeypatch.setattr(executive.repository, "record_conversation_turn",
                        lambda **kw: saved.append(kw))
    async def fake_agent(prompt):
        return "Yes, about dogs."
    async def fake_delivery(text, source):
        pass
    monkeypatch.setattr(agent_runtime, "agent_reply", fake_agent)
    monkeypatch.setattr(executive, "deliver_agent_speech", fake_delivery)
    asyncio.run(executive.respond_to_user_speech("What about height?", "desktop-home"))
    assert [item["role"] for item in saved] == ["user", "assistant"]
    assert all(item["session_id"] == "jarvis-primary" for item in saved)
    assert saved[0]["text"] == "What about height?"
    assert saved[1]["text"] == "Yes, about dogs."


def test_camera_rejects_three_view_legacy_payload():
    import pytest
    from fastapi import HTTPException

    photos = [{"view": name, "jpeg_base64": "unused"}
              for name in ("left", "center", "right")]
    with pytest.raises(HTTPException, match="two freshly captured"):
        asyncio.run(execute_tool("inspect_environment", {
            "question": "What is in front of me?", "_capture_images": photos,
        }))


def test_camera_requires_one_left_and_one_right():
    import pytest
    from fastapi import HTTPException

    photos = [{"view": "left", "jpeg_base64": "unused"}] * 2
    with pytest.raises(HTTPException):
        asyncio.run(execute_tool("inspect_environment", {
            "question": "Describe surroundings", "_capture_images": photos,
        }))
