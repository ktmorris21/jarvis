"""Hardware-free tests for bounded, warning-focused Pi diagnostic uploads."""
import json
import sys
from datetime import datetime
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "voice"))
import diagnostics


class DiagnosticsTests(unittest.TestCase):
    def test_collector_uses_recent_filtered_journal_not_short_tail(self):
        commands = []

        def fake_run(argv, timeout=5):
            commands.append(argv)
            return "ok"

        with patch.object(diagnostics, "run", side_effect=fake_run):
            report = diagnostics.collect_sync()
        self.assertEqual(len(report["report_id"]), 12)
        self.assertEqual(len(report["sections"]), 4 + len(diagnostics.SERVICES)*2 + 3)
        journals = [cmd for cmd in commands if cmd[0] == "/usr/bin/journalctl"]
        self.assertEqual(len(journals), len(diagnostics.SERVICES) + 4)
        for command in journals:
            self.assertEqual(command[command.index("--since") + 1], "-30 minutes")
            self.assertIn("--grep", command)
            self.assertIn("--case-sensitive=no", command)
            self.assertNotIn("18", command)
        self.assertIn("nav_goal_(aborted|canceled)",
                      " ".join(journals[-2]))
        self.assertIn("journal:nav_goal_failures", report["sections"])
        self.assertIn("journal:voice_stop", report["sections"])
        self.assertIn("journal:ros_stop", report["sections"])
        voice = next(cmd for cmd in journals
                     if "jarvis-agents-voice.service" in cmd)
        self.assertIn("Stop command failed", " ".join(voice))
        self.assertIn("operator stop goal", " ".join(" ".join(cmd) for cmd in journals))


    def test_redacts_credentials_and_bounds_sections(self):
        data = "bearer private123 token=mytoken password:xyz api_key=something"
        cleaned = diagnostics.clean(data)
        for secret in ("private123", "mytoken", "xyz", "something"):
            self.assertNotIn(secret, cleaned)
        self.assertLessEqual(len(diagnostics.clean("z"*10000)), diagnostics.MAX_SECTION)

    def test_newest_first_journal_truncation_keeps_recent_error(self):
        # journalctl --grep with -n produces reverse chronological output.
        recent = "2026-11-19 21:22:38 [ERROR] Nav2 controller failure\n"
        older = "2026-11-19 21:02:50 [WARN] old warning\n"
        output = recent + older * 200
        with patch.object(diagnostics.subprocess, "run") as fake:
            fake.return_value.stdout = output
            fake.return_value.stderr = ""
            fake.return_value.returncode = 0
            collected = diagnostics.run(["/usr/bin/journalctl", "--grep", "error", "-n", "80"])
        self.assertTrue(collected.startswith(recent))
        self.assertNotIn("21:02:50", collected[-20:])
        self.assertLessEqual(len(collected), diagnostics.MAX_SECTION)
        self.assertNotIn(recent, diagnostics.clean(output))

    def test_timestamped_goal_context_queries_correct_time_window(self):
        event = ('2026-11-19T21:22:31-06:00 host NAV_DIAG_LOCAL '
                 '{"kind":"nav_goal_aborted","goal_id":"'
                 + "a" * 32 + '"}')
        calls = []

        def fake_run(argv, timeout=5):
            calls.append(argv)
            if "jarvis-bridge@shadowfax.service" in argv:
                return event + "\n"
            return "2026-11-19T21:22:30-06:00 [WARN] Controller failure"

        with patch.object(diagnostics, "run", side_effect=fake_run):
            matches = diagnostics.recent_goal_events()
            self.assertEqual(len(matches), 1)
            detail = diagnostics.goal_failure_context(*matches[0])
        self.assertIn("GOAL FAILURE", detail)
        self.assertIn("Controller failure", detail)
        nav_call = calls[-1]
        self.assertEqual(nav_call[nav_call.index("--since")+1],
                         "2026-11-19T21:22:25-06:00")
        self.assertEqual(nav_call[nav_call.index("--until")+1],
                         "2026-11-19T21:22:34-06:00")

    def test_goal_event_limit_and_deduplication(self):
        lines = []
        for i in (38, 38, 31, 29):
            lines.append('2026-11-19T21:22:%02d-06:00 host NAV_DIAG_LOCAL ' % i
                         + '{"kind":"nav_goal_aborted","goal_id":"'
                         + ("%032x" % i) + '"}')
        with patch.object(diagnostics, "run", return_value="\n".join(lines)):
            found = diagnostics.recent_goal_events()
        self.assertEqual(len(found), diagnostics.MAX_GOAL_CONTEXTS)
        self.assertEqual([v[0].second for v in found], [38, 31])

    def test_context_keeps_failure_marker_even_if_nav2_is_noisy(self):
        event = "2026-11-19T21:22:31-06:00 GOAL ABORT"
        with patch.object(diagnostics, "run", return_value="old message\n"*500):
            context = diagnostics.goal_failure_context(
                datetime.fromisoformat("2026-11-19T21:22:31-06:00"), event)
        self.assertTrue(context.startswith("GOAL FAILURE " + event))
        self.assertLessEqual(len(context), diagnostics.MAX_SECTION)


    def test_report_stays_bounded_if_every_journal_is_noisy(self):
        def noisy_journals(argv, timeout=5):
            return "X" * diagnostics.MAX_SECTION if argv[0] == "/usr/bin/journalctl" else "ok"

        with patch.object(diagnostics, "run", side_effect=noisy_journals):
            report = diagnostics.collect_sync()
        self.assertLessEqual(len(json.dumps(report)), diagnostics.MAX_REPORT)
        self.assertTrue(all(len(v) <= diagnostics.MAX_SECTION
                            for k, v in report["sections"].items()
                            if k.startswith("journal:")))


if __name__ == "__main__":
    unittest.main()
