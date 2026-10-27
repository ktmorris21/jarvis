"""Load the shared, human-editable Jarvis identity and personality."""

from pathlib import Path

IDENTITY_PATH = Path(__file__).with_name("jarvis_identity.md")


def identity_instructions() -> str:
    """Read from disk so Core deployments and local edits share one source."""
    return IDENTITY_PATH.read_text(encoding="utf-8").strip()


# Compatibility for existing imports; new code should call identity_instructions().
IDENTITY = identity_instructions()
