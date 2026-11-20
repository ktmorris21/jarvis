"""No ROS, Vosk, or hardware required: persistent voice-stop client tests."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "voice"))
from ros_stop_client import PersistentStopClient


class FakeStdin:
    def __init__(self):
        self.writes = []

    def write(self, data):
        self.writes.append(data)

    async def drain(self):
        pass


class FakeProcess:
    def __init__(self, ready=True, response=None):
        self.returncode = None
        self.stdin = FakeStdin()
        self.stdout = asyncio.StreamReader()
        if ready:
            self.stdout.feed_data(b'{"type":"ready","service":"/jarvis/motion/stop"}\n')
        if response is not None:
            self.stdout.feed_data(response)

    def terminate(self):
        self.returncode = 0

    def kill(self):
        self.returncode = -9

    async def wait(self):
        return self.returncode


class StopClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_prewarms_once_and_reuses_connection(self):
        proc = FakeProcess(response=(b'{"type":"result","success":true,"elapsed_ms":8}\n'
                                     b'{"type":"result","success":true,"elapsed_ms":7}\n'))
        with patch("ros_stop_client.asyncio.create_subprocess_exec",
                   new_callable=AsyncMock, return_value=proc) as spawn:
            client = PersistentStopClient()
            await client.start()
            await client.stop()
            await client.stop()
            self.assertEqual(proc.stdin.writes, [b"STOP\n", b"STOP\n"])
            self.assertEqual(spawn.await_count, 1)
            await client.close()

    async def test_rejected_request_is_not_reported_successful(self):
        proc = FakeProcess(response=b'{"type":"result","success":false,"reason":"stop unavailable"}\n')
        with patch("ros_stop_client.asyncio.create_subprocess_exec",
                   new_callable=AsyncMock, return_value=proc):
            client = PersistentStopClient()
            await client.start()
            with self.assertRaisesRegex(RuntimeError, "stop unavailable"):
                await client.stop()
            self.assertIsNone(client.process)

    async def test_timeout_discards_worker_to_prevent_stale_ack(self):
        proc = FakeProcess()
        with patch("ros_stop_client.asyncio.create_subprocess_exec",
                   new_callable=AsyncMock, return_value=proc), \
             patch("ros_stop_client.STOP_TIMEOUT", 0.01):
            client = PersistentStopClient()
            await client.start()
            with self.assertRaises(asyncio.TimeoutError):
                await client.stop()
            self.assertIsNone(client.process)
            self.assertEqual(proc.returncode, 0)

    async def test_initialization_failure_is_explicit(self):
        proc = FakeProcess(ready=False)
        proc.stdout.feed_data(b'{"type":"error","reason":"stop_service_unavailable"}\n')
        with patch("ros_stop_client.asyncio.create_subprocess_exec",
                   new_callable=AsyncMock, return_value=proc):
            client = PersistentStopClient()
            with self.assertRaisesRegex(RuntimeError, "stop_service_unavailable"):
                await client.start()
            self.assertIsNone(client.process)


if __name__ == "__main__":
    unittest.main()
