"""Persistent camera-worker transport and resource reporting (no camera required)."""
import asyncio
import base64
import json
from pathlib import Path

from clients.voice import environment_camera
from clients.voice.camera_worker import process_stats


def test_resource_snapshot_reports_process_memory():
    result = process_stats(__import__("os").getpid())
    assert result["rss_mib"] > 0
    assert result["cpu_seconds"] >= 0
    assert result["processes"] >= 1


def test_two_view_inspection_uses_camera_socket(monkeypatch, tmp_path):
    socket = tmp_path / "camera.sock"
    received = []
    jpeg = bytes.fromhex("ffd8ffe0") + b"test-jpeg"
    async def handler(reader, writer):
        request = json.loads(await reader.readline())
        received.append(request)
        writer.write(json.dumps({
            "ok": True, "jpeg_base64": base64.b64encode(jpeg).decode("ascii")
        }).encode() + b"\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    class Head:
        proc = type("FakeProcess", (), {"returncode": None})()
        def __init__(self):
            self.states = []
        async def set(self, state):
            self.states.append(state)

    async def exercise():
        server = await asyncio.start_unix_server(handler, str(socket))
        try:
            monkeypatch.setattr(environment_camera, "WORKER_SOCKET", socket)
            head = Head()
            photos = await environment_camera.capture_environment(head, trace_id="test123")
            assert [p["view"] for p in photos] == ["left", "right"]
            assert all(base64.b64decode(p["jpeg_base64"]) == jpeg for p in photos)
            assert head.states == ["scan_left", "scan_right", "idle"]
            assert received == [{"command": "capture"}, {"command": "capture"}]
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(exercise())
