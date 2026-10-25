"""Regression checks: there is only one conversational engine."""
import asyncio

from jarvis_core import executive


def test_agent_failure_is_visible_not_legacy(monkeypatch):
    from jarvis_core import agent_runtime
    from jarvis_core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    async def failing_agent(text):
        raise RuntimeError("Test SDK failure")
    captured = []
    async def capture_speech(reply, source):
        captured.append((reply, source))
    monkeypatch.setattr(agent_runtime, "agent_reply", failing_agent)
    monkeypatch.setattr(executive, "deliver_agent_speech", capture_speech)

    asyncio.run(executive.respond_to_user_speech("Hello?", "desktop-home"))
    assert len(captured) == 1
    assert "unavailable" in captured[0][0].lower()
    assert "backup cognition" in captured[0][0].lower()


def test_success_uses_agent_reply(monkeypatch):
    from jarvis_core import agent_runtime
    from jarvis_core.config import settings
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    async def responding_agent(text):
        assert text == "Test me"
        return "Hello from the agent"
    captured = []
    async def capture_speech(reply, source):
        captured.append(reply)
    monkeypatch.setattr(agent_runtime, "agent_reply", responding_agent)
    monkeypatch.setattr(executive, "deliver_agent_speech", capture_speech)
    asyncio.run(executive.respond_to_user_speech("Test me", "desktop-home"))
    assert captured == ["Hello from the agent"]
