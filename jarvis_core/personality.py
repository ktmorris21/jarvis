"""Compatibility shim: character guidance now lives in jarvis_identity.md.

New callers should use identity.identity_instructions() directly.
"""

from .identity import identity_instructions


def personality_instructions() -> str:
    """Legacy entry point; no longer composes a second personality prompt."""
    return identity_instructions()
