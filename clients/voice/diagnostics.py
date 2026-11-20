"""Bounded, read-only diagnostics for an explicit local voice request.

No arbitrary shell, sensitive voice transcripts, environment dumps or credential
files. Railway stores the result in its operational logs, not Jarvis memory.
"""
import asyncio
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
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
MAX_GOAL_CONTEXTS = 2
GOAL_FAILURE_MATCH = r"nav_goal_aborted|RELATIVE_MOTION_ABORT|exploration_goal_failed"
# Capture relevant ROS2 planner/controller/BT errors around a failed goal.
NAV2_CONTEXT_MATCH = (
    r"\[(?:WARN|WARNING|ERROR|FATAL)\]"
    r"|failed to plan|no valid path|exceeded maximum iterations"
    r"|navigate_to_pose|follow_path|compute_path_to_pose"
    r"|bt_navigator|controller_server|planner_server"
    r"|ActionServer|Goal failed|goal was aborted"
)
EVENT_LINE_TIME = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))\s"
)
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

def clean(text, *, newest_first=False):
    # Defense in depth: diagnostics should never intentionally include secrets.
    text = re.sub(r"(?i)(bearer\s+)[^\s]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)((?:token|password|api_key|secret)\s*[=:]\s*)[^\s,]+",
                  r"\1[REDACTED]", text)
    # journalctl --grep with -n implicitly returns newest FIRST. Preserve the
    # most recent evidence; truncating from the end loses the actual failure.
    return text[:MAX_SECTION] if newest_first else text[-MAX_SECTION:]

def run(argv, timeout=5):
    try:
        result = subprocess.run(argv, capture_output=True, text=True,
                                timeout=timeout, check=False)
        output = (result.stdout or "") + (result.stderr or "")
        return clean(output or "(no output)", newest_first="--grep" in argv) + (f" [exit={result.returncode}]" if result.returncode else "")
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"unavailable: {type(exc).__name__}"

def recent_goal_events():
    """Find recent timestamped goal failures in Pi-side journals."""
    output = run([
        "/usr/bin/journalctl",
        "-u", "jarvis-bridge@shadowfax.service",
        "-u", "jarvis-nav2.service",
        "--since", JOURNAL_WINDOW,
        "--grep", GOAL_FAILURE_MATCH, "--case-sensitive=no",
        "-n", "12", "--no-pager", "-o", "short-iso",
    ], timeout=6)
    events = []
    seen = set()
    for line in output.splitlines():
        match = EVENT_LINE_TIME.match(line)
        if match is None:
            continue
        try:
            when = datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
        except ValueError:
            continue
        goal_id = re.search(r'goal_id[^0-9a-f]*([0-9a-f]{32})', line)
        identity = goal_id.group(1) if goal_id else when.isoformat()
        if identity in seen:
            continue
        seen.add(identity)
        events.append((when, line))
        if len(events) >= MAX_GOAL_CONTEXTS:
            break
    return events


def goal_failure_context(when, event):
    """Query Nav2 messages within a narrow window around one failed goal."""
    before = (when - timedelta(seconds=6)).isoformat(timespec="seconds")
    after = (when + timedelta(seconds=3)).isoformat(timespec="seconds")
    details = run([
        "/usr/bin/journalctl", "-u", "jarvis-nav2.service",
        "--since", before, "--until", after,
        "--grep", NAV2_CONTEXT_MATCH, "--case-sensitive=no",
        "-n", "50", "--no-pager", "-o", "short-iso",
    ], timeout=6)
    # Keep the event marker and newest nearby Nav2 errors, even if verbose.
    return clean("GOAL FAILURE " + event[:420] + "\n" + details,
                 newest_first=True)


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
    # Diagnose the Pi-local voice stop route, which bypasses Railway entirely.
    # Match only explicit stop/wake/control outcome messages. Never upload
    # ordinary conversations, unrestricted STT text, or microphone data.
    sections["journal:voice_stop"] = run([
        "/usr/bin/journalctl", "-u", "jarvis-agents-voice.service",
        "--since", JOURNAL_WINDOW,
        "--grep", r"\[LOCAL\].*(?:stop|[Ss]top request failed|Grammar transcript='(?:stop|stop moving|stop movement)')"
                  r"|\[WAKE\] Acknowledged|Stop command failed",
        "--case-sensitive=no",
        "-n", "35", "--no-pager", "-o", "short-iso",
    ], timeout=6)
    sections["journal:ros_stop"] = run([
        "/usr/bin/journalctl", "-u", "jarvis-nav2.service",
        "-u", "jarvis-drive@shadowfax.service",
        "--since", JOURNAL_WINDOW,
        "--grep", r"VOICE_STOP_|GOAL STOP INHIBIT|operator stop goal",
        "--case-sensitive=no",
        "-n", "35", "--no-pager", "-o", "short-iso",
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
    # Correlate up to two recent failed goals to nearby Nav2 diagnostic lines.
    # No daemon or continuous log capture is needed.
    for index, (when, event) in enumerate(recent_goal_events(), 1):
        sections["nav_failure_context:" + str(index)] = goal_failure_context(when, event)
    report = {
        "report_id": report_id,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "sections": sections,
    }
    # Predictably cap the wire/log payload even when local commands are noisy.
    while len(json.dumps(report, ensure_ascii=True)) > MAX_REPORT and any(
            key.startswith("journal:") and len(val) > 200
            for key, val in sections.items()):
        key = max((key for key in sections if key.startswith("journal:")),
                  key=lambda k: len(sections[k]))
        sections[key] = sections[key][:max(200, len(sections[key]) // 2)]
    return report

async def collect_diagnostics():
    return await asyncio.to_thread(collect_sync)
