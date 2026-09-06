import asyncio

from jarvis_core.executive import send_command
from jarvis_core.models import Command
from jarvis_core.state import InterfaceConnection, state


class FakeWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, payload):
        self.messages.append(payload)


def test_targeted_routing_hits_only_target():
    async def run():
        state.interfaces.clear()
        desktop_ws = FakeWebSocket()
        picar_ws = FakeWebSocket()
        await state.register(InterfaceConnection("desktop-home", "desktop", ["speaker"], desktop_ws))
        await state.register(InterfaceConnection("picar-main", "mobile_body", ["look", "move", "stop"], picar_ws))

        ok, route = await send_command(Command(target="picar-main", ability="look", data={"pan_deg": 20}))
        assert ok is True
        assert route == "picar-main"
        assert len(picar_ws.messages) == 1
        assert len(desktop_ws.messages) == 0
        assert picar_ws.messages[0]["ability"] == "look"

    asyncio.run(run())


def test_target_rejects_unadvertised_capability():
    async def run():
        state.interfaces.clear()
        ws = FakeWebSocket()
        await state.register(InterfaceConnection("picar-main", "mobile_body", ["look"], ws))
        ok, message = await send_command(Command(target="picar-main", ability="move"))
        assert ok is False
        assert "does not advertise" in message
        assert ws.messages == []

    asyncio.run(run())
