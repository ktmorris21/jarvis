import asyncio

from jarvis_core.agent_runtime import (
    baseline_context, deliver_status_result, get_robot_status_data,
    search_memory_data,
)
from jarvis_core.config import settings


def test_baseline_does_not_include_transcript(monkeypatch):
    from jarvis_core.agent_runtime import repository
    monkeypatch.setattr(repository, 'goals', lambda *args: [])
    text = baseline_context()
    assert "one persistent agent" in text
    assert "get_robot_status" in text
    assert "search_memories" in text


def test_autonomous_curiosity_disabled_by_default():
    assert settings.autonomous_curiosity_enabled is False


def test_status_tool_matches_command_and_waits(monkeypatch):
    from jarvis_core import executive
    from jarvis_core.agent_runtime import _pending_status

    async def fake_send(command):
        asyncio.get_running_loop().call_soon(
            deliver_status_result,
            {"command_id": command.command_id, "status": "complete",
             "result": {"robot_id": "picar-main", "lidar": {"active": True}}}
        )
        return True, "picar-ros"

    monkeypatch.setattr(executive, "send_command", fake_send)
    result = asyncio.run(get_robot_status_data())
    assert result["available"]
    assert result["status"]["lidar"]["active"] is True
    assert not _pending_status


def test_status_tool_unavailable(monkeypatch):
    from jarvis_core import executive

    async def fake_send(command):
        return False, "Robot offline"

    monkeypatch.setattr(executive, "send_command", fake_send)
    assert asyncio.run(get_robot_status_data()) == {
        "available": False, "reason": "Robot offline"
    }


def test_memory_tool_limits_results(monkeypatch):
    from jarvis_core.agent_runtime import memory

    def fake_retrieve(query, limit):
        assert limit == 5
        return [{"id": "m1", "memory_type": "episodic", "content": "A fact",
                 "created_at": "2026-10-25T00:00:00Z"}]

    monkeypatch.setattr(memory, "retrieve", fake_retrieve)
    assert search_memory_data("LiDAR")[0]["content"] == "A fact"


def test_exploration_command_reaches_ros_bridge(monkeypatch):
    from jarvis_core import executive
    from jarvis_core.agent_runtime import exploration_command_data, _pending_status

    async def fake_send(command):
        assert command.target == "picar-ros"
        assert command.ability == "explore"
        assert command.data == {}
        asyncio.get_running_loop().call_soon(
            deliver_status_result,
            {"command_id": command.command_id, "status": "complete",
             "result": {"success": True, "message": "Exploration enabled"}})
        return True, "picar-ros"

    monkeypatch.setattr(executive, "send_command", fake_send)
    result = asyncio.run(exploration_command_data("explore"))
    assert result["available"] is True
    assert result["success"] is True
    assert not _pending_status


def test_exploration_tool_fails_closed_when_ros_unavailable(monkeypatch):
    from jarvis_core import executive
    from jarvis_core.agent_runtime import exploration_command_data
    from jarvis_core.abilities import CORE_TOOLS, execute_tool
    from fastapi import HTTPException
    import pytest

    async def fake_send(command):
        return False, "Robot disconnected"

    monkeypatch.setattr(executive, "send_command", fake_send)
    for name in ("explore", "stop_exploring", "exploration_status"):
        assert name in CORE_TOOLS
        assert asyncio.run(execute_tool(name, {})) == {
            "available": False, "success": False, "reason": "Robot disconnected"
        }
        with pytest.raises(HTTPException):
            asyncio.run(execute_tool(name, {"unexpected": True}))


def test_operational_status_guidance_is_shared_across_identities(monkeypatch):
    from jarvis_core import agent_runtime
    from jarvis_core.agent_runtime import repository

    monkeypatch.setattr(repository, "goals", lambda *args: [])
    monkeypatch.setattr(agent_runtime, "identity_instructions",
                        lambda: "# Test identity")
    monkeypatch.setattr(agent_runtime, "current_identity_profile",
                        lambda: "bravo")
    snapshot = {"available": True, "status": {
        "lidar": {"active": True}, "mapping": {"available": True},
        "pose": {"available": True}, "battery": {"available": True},
        "exploration": {"available": True, "mode": "exploring"},
    }}
    text = baseline_context(robot_status_context=snapshot)
    assert "# Test identity" in text
    assert "general status or systems-health request" in text
    assert "Navigation/exploration status is not a substitute for systems status" in text
    assert '"mode": "exploring"' in text


def test_session_reset_targets_only_prior_agent_conversation(monkeypatch):
    from jarvis_core import agent_runtime
    from jarvis_core.agent_runtime import repository
    import sys
    import types

    cleared = []
    records = {}

    class FakeSession:
        @classmethod
        def from_url(cls, session_id, **kwargs):
            assert session_id == agent_runtime.PREVIOUS_SESSION_ID
            assert kwargs["create_tables"] is True
            return cls()

        async def clear_session(self):
            cleared.append(True)

    monkeypatch.setitem(
        sys.modules, "agents.extensions.memory",
        types.SimpleNamespace(SQLAlchemySession=FakeSession),
    )
    monkeypatch.setattr(agent_runtime, "_agent_session_url",
                        lambda: "sqlite+aiosqlite:///test.db")
    monkeypatch.setattr(repository, "get_state",
                        lambda key: records.get(key))
    monkeypatch.setattr(repository, "upsert_state",
                        lambda key, kind, value: records.__setitem__(key, value))

    asyncio.run(agent_runtime._clear_previous_agent_history_once())
    asyncio.run(agent_runtime._clear_previous_agent_history_once())
    assert len(cleared) == 1
    assert records[agent_runtime.SESSION_RESET_MARKER]["cleared_session_id"] == (
        agent_runtime.PREVIOUS_SESSION_ID
    )
    assert agent_runtime.SESSION_ID != agent_runtime.PREVIOUS_SESSION_ID


def test_inspect_environment_uses_fresh_pi_images(monkeypatch):
    from jarvis_core import executive, agent_runtime
    from jarvis_core.agent_runtime import _pending_status

    photos = [
        {"view": "left", "jpeg_base64": "test-left"},
        {"view": "right", "jpeg_base64": "test-right"},
    ]

    async def fake_send(command):
        assert command.target == "picar-voice"
        assert command.ability == "capture_environment"
        asyncio.get_running_loop().call_soon(
            deliver_status_result, {
                "command_id": command.command_id, "status": "complete",
                "result": {"images": photos},
            })
        return True, "picar-voice"

    async def fake_vision(name, args):
        assert name == "inspect_environment"
        assert args == {"question": "What is in front of me?",
                        "_capture_images": photos}
        return {"available": True, "findings": "A hallway and doorway."}

    monkeypatch.setattr(executive, "send_command", fake_send)
    monkeypatch.setattr(agent_runtime, "execute_tool", fake_vision)
    result = asyncio.run(agent_runtime.inspect_environment_data(
        "What is in front of me?"))
    assert result["available"] is True
    assert result["findings"] == "A hallway and doorway."
    assert not _pending_status


def test_camera_result_does_not_persist_image_payload(monkeypatch):
    from jarvis_core import executive
    from jarvis_core.models import InterfaceEvent
    records = []
    delivered = []
    monkeypatch.setattr(executive.repository, "complete_action_by_command",
                        lambda command_id, result: records.append(result))
    from jarvis_core import agent_runtime
    monkeypatch.setattr(agent_runtime, "deliver_status_result",
                        lambda event: delivered.append(event))
    image = "very-sensitive-jpeg-base64"
    event = InterfaceEvent(event="COMMAND_RESULT", data={
        "command_id": "camera-test", "ability": "capture_environment",
        "status": "complete",
        "result": {"images": [{"view": "left", "jpeg_base64": image}]},
    })
    outcome = asyncio.run(executive.handle_event(event, source="picar-voice"))
    assert outcome["persisted"] is False
    assert delivered[0]["result"]["images"][0]["jpeg_base64"] == image
    assert image not in str(records)
