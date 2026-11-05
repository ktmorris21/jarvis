"""Identity selection must be persistent, bounded, and independent of history."""
import asyncio

import pytest
from fastapi import HTTPException

from jarvis_core import identity
from jarvis_core.abilities import CORE_TOOLS, execute_tool


def test_alpha_is_existing_identity():
    assert identity.PROFILE_FILES["alpha"] == "jarvis_identity.md"
    assert "favorite color is blue" in identity.identity_instructions("alpha")


def test_profiles_are_independent():
    texts = [identity.identity_instructions(name)
             for name in ("alpha", "bravo", "charlie")]
    assert len(set(texts)) == 3
    assert "methodical" in texts[1]
    assert "playful" in texts[2]


def test_persisted_selection(monkeypatch):
    stored = {}

    monkeypatch.setattr(identity.repository, "get_state", lambda key: stored.get(key))

    def save(key, kind, value):
        stored[key] = value

    monkeypatch.setattr(identity.repository, "upsert_state", save)
    assert identity.current_identity_profile() == "alpha"
    result = identity.select_identity_profile("bravo")
    assert result == {
        "success": True, "previous_profile": "alpha",
        "active_profile": "bravo",
    }
    assert identity.current_identity_profile() == "bravo"
    assert "methodical" in identity.identity_instructions()


def test_bad_selection_does_not_change_profile(monkeypatch):
    stored = {"profile": "alpha"}
    monkeypatch.setattr(identity.repository, "get_state", lambda key: stored)
    monkeypatch.setattr(identity.repository, "upsert_state",
                        lambda *args: pytest.fail("Should not persist"))
    with pytest.raises(ValueError):
        identity.select_identity_profile("../untrusted")


def test_tool_schema_and_validation(monkeypatch):
    assert "set_identity_profile" in CORE_TOOLS
    assert "get_identity_profile" in CORE_TOOLS
    monkeypatch.setattr(identity.repository, "get_state",
                        lambda key: {"profile": "alpha"})
    assert asyncio.run(execute_tool("get_identity_profile", {})) == {
        "active_profile": "alpha"
    }
    with pytest.raises(HTTPException):
        asyncio.run(execute_tool("set_identity_profile", {"profile": "invalid"}))
    with pytest.raises(HTTPException):
        asyncio.run(execute_tool("get_identity_profile", {"unwanted": True}))
