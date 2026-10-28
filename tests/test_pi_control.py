"""Pi control bridge regression tests: fixed commands and strict input checks."""
import asyncio

import pytest

from body_services.picar import control_bridge as bridge
from jarvis_core import abilities


def run(coro):
    return asyncio.run(coro)


def test_all_management_tools_are_shared():
    names = {t["name"] for t in abilities.tool_schemas()}
    assert {"get_audio_levels", "set_audio_level", "get_lidar_service",
            "set_lidar_service", "reboot_pi"} <= names


def test_invalid_audio_arguments_never_reach_pi(monkeypatch):
    async def should_not_call(*args, **kwargs):
        raise AssertionError("Pi bridge should not be contacted")
    from jarvis_core import agent_runtime
    monkeypatch.setattr(agent_runtime, "pi_control_data", should_not_call)
    with pytest.raises(Exception):
        run(abilities.execute_tool("set_audio_level",
                                   {"device": "speaker", "percent": 101}))
    with pytest.raises(Exception):
        run(abilities.execute_tool("set_audio_level",
                                   {"device": "microphone", "percent": True}))
    with pytest.raises(Exception):
        run(abilities.execute_tool("reboot_pi", {"confirmation": "yes"}))


def test_fixed_amixer_command(monkeypatch):
    observed = []
    async def fake_run(*args, **kwargs):
        observed.append(args)
        return "Front Left: Playback 40 [40%] [-20.00dB]"
    monkeypatch.setattr(bridge, "run_fixed", fake_run)
    monkeypatch.setenv("JARVIS_ALSA_DEVICE", "default")
    monkeypatch.setenv("JARVIS_SPEAKER_CONTROL", "Speaker")
    result = run(bridge.execute("set_audio_level",
                               {"device": "speaker", "percent": 40}))
    assert result["percent"] == 40
    assert observed[0] == ("/usr/bin/amixer", "-D", "default",
                           "sset", "Speaker", "40%")
    assert observed[1] == ("/usr/bin/amixer", "-D", "default",
                           "sget", "Speaker")


def test_lidar_service_uses_fixed_name(monkeypatch):
    observed = []
    async def fake_run(*args, **kwargs):
        observed.append(args)
        return ""
    monkeypatch.setattr(bridge, "run_fixed", fake_run)
    result = run(bridge.execute("set_lidar_service", {"running": False}))
    assert result["controls_entire_mapping_stack"]
    assert observed == [("/usr/bin/sudo", "-n", "/usr/bin/systemctl",
                          "stop", "jarvis-mapping@shadowfax.service")]


def test_reboot_disabled_by_default(monkeypatch):
    monkeypatch.delenv("JARVIS_ALLOW_REMOTE_REBOOT", raising=False)
    with pytest.raises(RuntimeError, match="disabled"):
        run(bridge.execute("reboot_pi",
                           {"confirmation": "REBOOT JARVIS NOW"}))


def test_wrong_operations_rejected():
    with pytest.raises(ValueError):
        run(bridge.execute("set_lidar_service", {"running": "true"}))
    with pytest.raises(ValueError):
        run(bridge.execute("set_audio_level", {"device": "speaker",
                                               "percent": "50"}))
    with pytest.raises(ValueError):
        run(bridge.execute("arbitrary_shell", {"command": "whoami"}))


def test_core_routes_pi_command_and_waits_for_result(monkeypatch):
    from jarvis_core import agent_runtime, executive

    async def fake_send(command):
        assert command.target == "picar-control"
        assert command.ability == "get_audio_levels"
        asyncio.get_running_loop().call_soon(
            agent_runtime.deliver_status_result,
            {"command_id": command.command_id, "status": "complete",
             "result": {"speaker": {"percent": 45}}})
        return True, "picar-control"

    monkeypatch.setattr(executive, "send_command", fake_send)
    result = run(agent_runtime.pi_control_data("get_audio_levels", {}))
    assert result["available"] is True
    assert result["speaker"]["percent"] == 45
    assert not agent_runtime._pending_status
