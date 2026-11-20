"""Hardware-free tests for bounded, warning-focused Pi diagnostic uploads."""
import sys
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
        self.assertEqual(len(report["sections"]), 4 + len(diagnostics.SERVICES)*2 + 1)
        journals = [cmd for cmd in commands if cmd[0] == "/usr/bin/journalctl"]
        self.assertEqual(len(journals), len(diagnostics.SERVICES) + 1)
        for command in journals:
            self.assertEqual(command[command.index("--since") + 1], "-30 minutes")
            self.assertIn("--grep", command)
            self.assertIn("--case-sensitive=no", command)
            self.assertNotIn("18", command)
        self.assertIn("nav_goal_(aborted|canceled)",
                      " ".join(journals[-1]))
        self.assertIn("journal:nav_goal_failures", report["sections"])

    def test_redacts_credentials_and_bounds_sections(self):
        data = "bearer private123 token=mytoken password:xyz api_key=something"
        cleaned = diagnostics.clean(data)
        for secret in ("private123", "mytoken", "xyz", "something"):
            self.assertNotIn(secret, cleaned)
        self.assertLessEqual(len(diagnostics.clean("z"*10000)), diagnostics.MAX_SECTION)

    def test_report_stays_bounded_if_every_journal_is_noisy(self):
        with patch.object(diagnostics, "run", return_value="X"*10000):
            report = diagnostics.collect_sync()
        self.assertLessEqual(len(str(report)), diagnostics.MAX_REPORT)
        self.assertTrue(all(len(v) <= diagnostics.MAX_SECTION
                            for k, v in report["sections"].items()
                            if k.startswith("journal:")))


if __name__ == "__main__":
    unittest.main()
