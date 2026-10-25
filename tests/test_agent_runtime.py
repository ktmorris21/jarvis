import asyncio

import pytest

from jarvis_core.agent_runtime import (
    baseline_context, deliver_status_result, get_robot_status_data,
    search_memory_data,
)
from jarvis_core.config import settings


def test_baseline_does_not_include_transcript():
    text = baseline_context()
    assert "one persistent agent" in text
    assert "get_robot_status" in text
    assert "search_memories" in text


def test_autonomous_curiosity_disabled_by_default():
    assert settings.autonomous_curiosity_enabled is False


@pytest.mark.asyncio
async def test_status_tool_matches_command_and_waits(monkeypatch):
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
    result = await get_robot_status_data()
    assert result["available"]
    assert result["status"]["lidar"]["active"] is True
    assert not _pending_status


@pytest.mark.asyncio
async def test_status_tool_unavailable(monkeypatch):
    from jarvis_core import executive

    async def fake_send(command):
        return False, "Robot offline"

    monkeypatch.setattr(executive, "send_command", fake_send)
    assert (await get_robot_status_data()) == {
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
