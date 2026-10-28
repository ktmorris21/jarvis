"""Boot readiness notice is one-shot per physical boot, not per voice process."""
import asyncio

from clients.voice import realtime_conversation as voice


def test_boot_announcement_only_once_per_boot(monkeypatch, tmp_path):
    boot = tmp_path / "boot_id"
    state = tmp_path / "announced"
    boot.write_text("boot-one\n")
    monkeypatch.setattr(voice, "BOOT_ID_FILE", boot)
    monkeypatch.setattr(voice, "BOOT_ANNOUNCED_FILE", state)
    assert voice.needs_boot_announcement() == "boot-one"
    state.write_text("boot-one\n")
    assert voice.needs_boot_announcement() is None
    boot.write_text("boot-two\n")
    assert voice.needs_boot_announcement() == "boot-two"


def test_boot_greeting_is_not_a_normal_dialogue():
    # Announcement must be outside send_turn and speak_turn; those persist
    # transcripts and/or create follow-up opportunities.
    import inspect
    source = inspect.getsource(voice.speak_boot_announcement)
    assert "send_turn(" not in source
    assert "speak_turn(" not in source
    assert "capture_followup(" not in source
    assert "capture_transcript(" not in source
    assert voice.BOOT_GREETING.endswith(".")
