"""Boot readiness notice is one-shot per physical boot, not per voice process."""
from pathlib import Path

from clients.voice import boot_notice as notice


def test_boot_announcement_only_once_per_boot(monkeypatch, tmp_path):
    boot = tmp_path / "boot_id"
    state = tmp_path / "announced"
    boot.write_text("boot-one\n")
    monkeypatch.setattr(notice, "BOOT_ID_FILE", boot)
    monkeypatch.setattr(notice, "BOOT_ANNOUNCED_FILE", state)
    assert notice.needs_boot_announcement() == "boot-one"
    notice.mark_boot_announced("boot-one")
    assert notice.needs_boot_announcement() is None
    boot.write_text("boot-two\n")
    assert notice.needs_boot_announcement() == "boot-two"


def test_startup_speech_is_not_a_conversation():
    # Source-level guard: the startup path must not invoke the existing
    # dialogue-turn machinery (and its follow-up listening window).
    voice_script = (Path(__file__).resolve().parents[1] /
                    "clients/voice/realtime_conversation.py").read_text()
    boot_block = voice_script.split("async def speak_boot_announcement(", 1)[1].split(
        "\nasync def main(", 1)[0]
    assert "send_turn(" not in boot_block
    assert "speak_turn(" not in boot_block
    assert "capture_followup(" not in boot_block
    assert "capture_transcript(" not in boot_block
    assert notice.BOOT_GREETING.endswith(".")
