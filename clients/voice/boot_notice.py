"""One-shot voice readiness marker scoped to the current physical Linux boot."""
from pathlib import Path

BOOT_ID_FILE = Path("/proc/sys/kernel/random/boot_id")
BOOT_ANNOUNCED_FILE = Path("/tmp/jarvis-realtime-announced-boot-id")
BOOT_GREETING = "Jarvis online and ready."


def needs_boot_announcement():
    """Return current Linux boot ID if the announcement has not yet succeeded."""
    boot_id = BOOT_ID_FILE.read_text(encoding="ascii").strip()
    if not boot_id:
        raise RuntimeError("Kernel boot ID is unavailable")
    try:
        announced = BOOT_ANNOUNCED_FILE.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        announced = None
    return boot_id if announced != boot_id else None


def mark_boot_announced(boot_id):
    """Mark only after playback has completed successfully."""
    if not boot_id or boot_id != BOOT_ID_FILE.read_text(encoding="ascii").strip():
        raise RuntimeError("Boot changed while announcing readiness")
    BOOT_ANNOUNCED_FILE.write_text(boot_id + "\n", encoding="ascii")
