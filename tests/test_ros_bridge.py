"""Protocol and persistence regression tests for read-only ROS bridge."""
from unittest.mock import AsyncMock, patch
import pytest
from jarvis_core.executive import handle_event
from jarvis_core.models import InterfaceEvent
from jarvis_core.state import InterfaceConnection, state

@pytest.mark.asyncio
async def test_ros_status_result_updates_world_state_only_for_known_bridge():
    connection = InterfaceConnection("picar-ros", "ros_status", ["get_robot_status"], AsyncMock())
    state.interfaces["picar-ros"] = connection
    observation = {"robot_id":"picar-main","observed_at":"2026-10-23T02:00:00+00:00",
                   "lidar":{"active":True},"mapping":{"available":True}}
    event = InterfaceEvent(event="COMMAND_RESULT",data={
        "command_id":"test-status","ability":"get_robot_status",
        "status":"complete","result":observation})
    try:
        with patch("jarvis_core.executive.repository") as repo, patch("jarvis_core.executive.memory") as memory:
            memory.form_from_event.return_value = []
            await handle_event(event, source="picar-ros")
            assert repo.upsert_state.call_count >= 1
            assert any(call.args[0] == "robot_status:picar-ros"
                       for call in repo.upsert_state.call_args_list)
    finally:
        state.interfaces.pop("picar-ros", None)

@pytest.mark.asyncio
async def test_unregistered_status_cannot_update_robot_state():
    event = InterfaceEvent(event="COMMAND_RESULT",data={
        "command_id":"test-other","ability":"get_robot_status","status":"complete",
        "result":{"robot_id":"picar-main","observed_at":"now"}})
    with patch("jarvis_core.executive.repository") as repo, patch("jarvis_core.executive.memory") as memory:
        memory.form_from_event.return_value = []
        await handle_event(event, source="not-a-bridge")
        assert not any(call.args[0].startswith("robot_status:")
                       for call in repo.upsert_state.call_args_list)
