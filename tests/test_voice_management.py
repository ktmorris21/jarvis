"""Unit checks for management voice phrases without Vosk, ROS or hardware."""
import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "voice"))
from local_commands import LocalCommands, normalize, PROMPTS, LOCAL_GRAMMAR, CLOSING_GRAMMAR, CLOSING_NORMALIZED


class LocalManagementCommandsTests(unittest.IsolatedAsyncioTestCase):
    def make_local(self, words):
        local = LocalCommands.__new__(LocalCommands)
        local._recognizer_model = object()
        local.pending = None
        local.pending_until = 0.0
        local.transcribe = lambda wav, grammar=None: words.pop(0)
        return local

    async def test_stop_local_and_non_disarming(self):
        local = self.make_local(["stop"])
        calls = []
        async def request():
            calls.append("ros_stop")
        local._stop_ros_goals = request
        self.assertEqual(await local.act(b""), (True, "Stop requested.", None))
        self.assertEqual(calls, ["ros_stop"])

    async def test_stop_works_with_pending_arm_confirmation(self):
        local = self.make_local(["arm motors", "stop"])
        async def request():
            return None
        local._stop_ros_goals = request
        await local.act(b"")
        self.assertEqual(await local.act(b""), (True, "Stop requested.", None))
        self.assertIsNone(local.pending)

    async def test_stop_failure_is_local(self):
        local = self.make_local(["stop"])
        async def request():
            raise RuntimeError("ROS unavailable")
        local._stop_ros_goals = request
        self.assertEqual(await local.act(b""),
            (True, "Stop command failed. Use the physical power switch.", None))

    async def test_upload_is_explicit_no_confirmation(self):
        local = self.make_local(["upload diagnostics"])
        handled, reply, deferred = await local.act(b"")
        self.assertTrue(handled)
        self.assertEqual(deferred, "diagnostics")
        self.assertIn("Uploading", reply)

    async def test_update_requires_confirmation(self):
        local = self.make_local(["update jarvis", "confirm update jarvis"])
        first = await local.act(b"")
        self.assertEqual(first, (True, PROMPTS["update"][0], None))
        second = await local.act(b"")
        self.assertEqual(second[2], "update")

    async def test_unrelated_speech_cancels_update(self):
        local = self.make_local(["update jarvis", "tell me a joke"])
        await local.act(b"")
        handled, _, deferred = await local.act(b"")
        self.assertFalse(handled)
        self.assertIsNone(deferred)
        self.assertIsNone(local.pending)

    async def test_nevermind_silently_closes_followup(self):
        for phrase in ("nevermind", "never mind"):
            local = self.make_local([phrase])
            self.assertTrue(await local.is_closing_phrase(b""))
            self.assertIn(phrase, CLOSING_GRAMMAR)
            self.assertIn(phrase, CLOSING_NORMALIZED)

    async def test_nevermind_with_extra_words_does_not_close(self):
        local = self.make_local(["never mind the navigation", "never mind the navigation"])
        self.assertFalse(await local.is_closing_phrase(b""))

    def test_grammar_contains_management_commands(self):
        for phrase in ("stop", "stop moving", "stop movement",
                       "update jarvis", "confirm update jarvis",
                       "upload diagnostics"):
            self.assertIn(phrase, LOCAL_GRAMMAR)
        self.assertEqual(normalize("Hey Jarvis, upload diagnostics please"),
                         "upload diagnostics")


if __name__ == "__main__":
    unittest.main()
