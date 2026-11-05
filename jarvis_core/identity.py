"""Select the human-editable Jarvis identity used for each new agent turn.

Only the identity layer changes; the agent's operational instructions,
tool permissions, and persistent conversation session remain unchanged.
"""
from pathlib import Path

from .persistence.repository import repository

PROFILE_FILES = {
    "alpha": "jarvis_identity.md",  # Preserve the existing identity verbatim.
    "bravo": "jarvis_identity_bravo.md",
    "charlie": "jarvis_identity_charlie.md",
}
DEFAULT_PROFILE = "alpha"
PROFILE_STATE_KEY = "jarvis:identity_profile"


def current_identity_profile() -> str:
    """Read persisted selection; default to Alpha on first deployment."""
    record = repository.get_state(PROFILE_STATE_KEY) or {}
    selected = record.get("profile", DEFAULT_PROFILE)
    return selected if selected in PROFILE_FILES else DEFAULT_PROFILE


def identity_instructions(profile: str | None = None) -> str:
    """Load only the selected Markdown file, fresh for each agent turn."""
    selected = profile or current_identity_profile()
    if selected not in PROFILE_FILES:
        raise ValueError("Unknown identity profile")
    path = Path(__file__).with_name(PROFILE_FILES[selected])
    instructions = path.read_text(encoding="utf-8").strip()
    if not instructions:
        raise ValueError(f"Identity profile {selected} is empty")
    return instructions


def select_identity_profile(profile: str) -> dict:
    """Persist only an explicit, installed profile, preserving old on error."""
    if not isinstance(profile, str) or profile not in PROFILE_FILES:
        raise ValueError("Profile must be alpha, bravo, or charlie")
    identity_instructions(profile)  # Verify file before updating persistence.
    previous = current_identity_profile()
    repository.upsert_state(
        PROFILE_STATE_KEY, "jarvis_setting", {"profile": profile}
    )
    return {"success": True, "previous_profile": previous, "active_profile": profile}


# Legacy import compatibility. Runtime callers must use identity_instructions().
IDENTITY = Path(__file__).with_name(PROFILE_FILES[DEFAULT_PROFILE]).read_text(
    encoding="utf-8"
).strip()
