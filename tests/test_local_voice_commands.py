"""Offline command router checks (no Vosk model, ROS or physical hardware)."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "voice"))
from local_commands import LocalCommands, normalize


def test_normalize_command():
    assert normalize("Hey Jarvis, arm motors please!") == "arm motors"
    assert normalize("Jarvis, power down.") == "power down"


def test_confirmation_and_unknown_routing():
    router = LocalCommands(model_path="/nonexistent/model")
    router._recognizer_model = object()
    router.transcribe = lambda wav: wav.decode()
    issued = []
    async def execute(action):
        issued.append(action)
        return "Motors armed."
    router._execute = execute

    async def run():
        assert await router.act(b"can you explain motor power") == (False, None, None)
        handled, prompt, action = await router.act(b"arm motors")
        assert handled and action is None and "confirm" in prompt.lower()
        assert issued == []
        assert await router.act(b"confirm arm motors") == (True, "Motors armed.", None)
        assert issued == ["arm"]
    asyncio.run(run())


def test_reboot_requires_separate_confirmation_and_disarm_immediate():
    router = LocalCommands(model_path="/nonexistent/model")
    router._recognizer_model = object()
    router.transcribe = lambda wav: wav.decode()
    issued = []
    async def execute(action):
        issued.append(action)
        return {"disarm": "Motors disarmed.", "reboot": "Rebooting Jarvis."}[action]
    router._execute = execute

    async def run():
        result = await router.act(b"reboot")
        assert result[0] and result[2] is None
        result = await router.act(b"confirm reboot")
        assert result == (True, "Rebooting Jarvis.", "reboot")
        assert issued == ["reboot"]
        result = await router.act(b"disarm motors")
        assert result == (True, "Motors disarmed.", None)
        assert issued[-1] == "disarm"
    asyncio.run(run())
