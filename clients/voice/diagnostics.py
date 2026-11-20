"""Bounded, read-only diagnostics for an explicit local voice request.

No arbitrary shell, sensitive voice transcripts, environment dumps or credential
files. Railway stores the result in its operational logs, not Jarvis memory.
"""
import asyncio
import re
import subprocess
from datetime import datetime, timezone
from uuid import uuid4

SERVICES = (
    "jarvis-nav2.service",
    "jarvis-mapping@shadowfax.service",
    "jarvis-drive@shadowfax.service",
    "jarvis-bridge@shadowfax.service",
)
MAX_SECTION = 2200
MAX_REPORT = 14500
# ROS launch often embeds "[WARN]" and "[ERROR]" in journal INFO messages.
# Match the message text rather than relying on systemd's severity field.
# Include navigation failures sent by the bridge at INFO severity.
JOURNAL_WINDOW = "-30 minutes"
JOURNAL_MATCH = (
    r"\[(?:WARN|WARNING|ERROR|FATAL)\]"
    r"|\b(?:warn(?:ing)?|error|fatal|critical|exception|traceback)\b"
    r"|nav_goal_(?:aborted|canceled)"
    r"|(?:goal|navigation|planner|controller|transform|lifecycle).{0,35}"
    r"(?:fail(?:ed|ure)?|abort(?:ed)?|reject(?:ed)?|timed out)"
    r"|(?:fail(?:ed|ure)?|abort(?:ed)?|reject(?:ed)?|timed out).{0,35}"
    r"(?:goal|navigation|planner|controller|transform|lifecycle)"
    r"|RELATIVE_MOTION_ABORT|VOICE_STOP_(?:CANCEL_FAILED|DRIVE_FAILED)"
    r"|motor_disarmed|drive_fault"
)

def clean(text):
    # Defense in depth: diagnostics should never intentionally include secrets.
    text = re.sub(r"(?i)(bearer\s+)[^\s]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)((?:token|password|api_key|secret)\s*[=:]\s*)[^\s,]+",
                  r"\1[REDACTED]", text)
    return text[-MAX_SECTION:]

def run(argv, timeout=5):
    try:
        result = subprocess.run(argv, capture_output=True, text=True,
                                timeout=timeout, check=False)
        output = (result.stdout or "") + (result.stderr or "")
        return clean(output or "(no output)") + (f" [exit={result.returncode}]" if result.returncode else "")
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"unavailable: {type(exc).__name__}"

def collect_sync():
    report_id = uuid4().hex[:12]
    sections = {
        "host": run(["/usr/bin/uptime"]),
        "git_head": run(["/usr/bin/git", "-C", "/home/shadowfax/jarvis", "rev-parse", "--short", "HEAD"]),
        "disk": run(["/usr/bin/df", "-h", "/"]),
        "memory": run(["/usr/bin/free", "-h"]),
    }
    for service in SERVICES:
        sections["service:" + service] = run(
            ["/usr/bin/systemctl", "is-active", service])
        sections["journal:" + service] = run([
            "/usr/bin/journalctl", "-u", service,
            "--since", JOURNAL_WINDOW,
            "--grep", JOURNAL_MATCH, "--case-sensitive=no",
            "-n", "80", "--no-pager", "-o", "short-iso",
        ], timeout=6)
    # Separate bounded navigation-failure history so a flood of warning
    # messages cannot evict the particular failed goal being investigated.
    sections["journal:nav_goal_failures"] = run([
        "/usr/bin/journalctl", "-u", "jarvis-bridge@shadowfax.service",
        "--since", JOURNAL_WINDOW,
        "--grep", "nav_goal_(aborted|canceled)|RELATIVE_MOTION_(ABORT|FINISHED)|VOICE_STOP_(CANCEL_FAILED|DRIVE_FAILED)",
        "--case-sensitive=no",
        "-n", "30", "--no-pager", "-o", "short-iso",
    ], timeout=6)
    report = {
        "report_id": report_id,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "sections": sections,
    }
    # Predictably cap the wire/log payload even when local commands are noisy.
    while len(str(report)) > MAX_REPORT and any(
            key.startswith("journal:") and len(val) > 200
            for key, val in sections.items()):
        key = max((key for key in sections if key.startswith("journal:")),
                  key=lambda k: len(sections[k]))
        sections[key] = sections[key][-max(200, len(sections[key]) // 2):]
    return report

async def collect_diagnostics():
    return await asyncio.to_thread(collect_sync)
