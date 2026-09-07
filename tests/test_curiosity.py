import asyncio

from jarvis_core.executive import maybe_explore_from_curiosity
from jarvis_core.persistence import init_db
from jarvis_core.persistence.db import SessionLocal
from jarvis_core.persistence.tables import GoalRow
from jarvis_core.state import InterfaceConnection, state


class FakeWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, payload):
        self.messages.append(payload)


def clear_goals():
    with SessionLocal() as session:
        session.query(GoalRow).delete()
        session.commit()


def test_curiosity_uses_generic_mobile_body_capability():
    async def run():
        init_db()
        clear_goals()
        state.interfaces.clear()
        state.curiosity = 1.0
        state.last_curiosity_action_at = None
        state.last_curiosity_ability = None

        ws = FakeWebSocket()
        await state.register(
            InterfaceConnection(
                "some-future-body",
                "mobile_body",
                ["look_around", "move", "stop"],
                ws,
            )
        )

        sent = await maybe_explore_from_curiosity()
        assert sent is True
        assert len(ws.messages) == 1
        assert ws.messages[0]["target"] == "some-future-body"
        assert ws.messages[0]["ability"] == "look_around"
        assert state.curiosity == 0.18

    asyncio.run(run())


def test_curiosity_alternates_to_small_move():
    async def run():
        init_db()
        clear_goals()
        state.interfaces.clear()
        state.curiosity = 1.0
        state.last_curiosity_action_at = None
        state.last_curiosity_ability = "look_around"

        ws = FakeWebSocket()
        await state.register(
            InterfaceConnection(
                "mobile-test",
                "mobile_body",
                ["look_around", "move", "stop"],
                ws,
            )
        )

        sent = await maybe_explore_from_curiosity()
        assert sent is True
        msg = ws.messages[0]
        assert msg["ability"] == "move"
        assert msg["data"]["speed"] == 18
        assert msg["data"]["duration_ms"] == 350

    asyncio.run(run())


def test_active_goal_suppresses_idle_curiosity():
    async def run():
        init_db()
        clear_goals()
        state.interfaces.clear()
        state.curiosity = 1.0
        state.last_curiosity_action_at = None

        ws = FakeWebSocket()
        await state.register(
            InterfaceConnection(
                "mobile-test",
                "mobile_body",
                ["look_around", "move", "stop"],
                ws,
            )
        )

        from jarvis_core.persistence.repository import repository
        repository.create_goal(
            kind="test",
            description="Higher priority work exists",
            priority=80,
        )

        sent = await maybe_explore_from_curiosity()
        assert sent is False
        assert ws.messages == []

    asyncio.run(run())
