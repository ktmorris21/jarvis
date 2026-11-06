#!/usr/bin/python3
"""Persistent, low-rate libcamera worker for Jarvis's OV5647 on Ubuntu 24.04.

Runs with /usr/bin/python3 for system OpenCV, but the child native executable
runs inside the verified isolated libcamera 0.3 meson environment. Clients
connect via a same-user, mode-0600 Unix socket. JPEGs are returned in memory.
"""
import asyncio
import base64
import contextlib
import json
import os
from pathlib import Path
import resource
import signal
import tempfile
import time

SOCKET_PATH = Path(os.environ.get(
    "JARVIS_CAMERA_WORKER_SOCKET", "/run/jarvis-camera/camera.sock"))
SOURCE = Path(os.environ.get(
    "JARVIS_LIBCAMERA_SOURCE", "/home/shadowfax/src/libcamera-0.3"))
NATIVE = Path(__file__).with_name("camera_native")
INTERVAL_MS = int(float(os.environ.get("JARVIS_CAMERA_INTERVAL_SECONDS", "2")) * 1000)
WIDTH, HEIGHT = 1280, 960
MAX_JPEG = 1_500_000


def process_stats(pid):
    """Aggregate native, meson, and helper-process resource usage."""
    try:
        processes = set()
        pending = [pid]
        while pending:
            child = pending.pop()
            if child in processes:
                continue
            processes.add(child)
            children = Path(f"/proc/{child}/task/{child}/children")
            if children.exists():
                pending.extend(int(item) for item in children.read_text().split())
        rss_kib, cpu, threads = 0, 0.0, 0
        clk = os.sysconf("SC_CLK_TCK")
        for child in processes:
            for line in Path(f"/proc/{child}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    rss_kib += int(line.split()[1])
                elif line.startswith("Threads:"):
                    threads += int(line.split()[1])
            stat = Path(f"/proc/{child}/stat").read_text()
            fields = stat[stat.rfind(")") + 2:].split()
            cpu += (int(fields[11]) + int(fields[12])) / clk
        return {"rss_mib": round(rss_kib / 1024, 1),
                "cpu_seconds": round(cpu, 2), "threads": threads,
                "processes": len(processes)}
    except (OSError, ValueError, IndexError):
        return {"available": False}


class CameraWorker:
    def __init__(self):
        self.proc = None
        self.lock = asyncio.Lock()
        self.captures = 0
        self.started = time.monotonic()

    async def start(self):
        if not NATIVE.is_file() or not os.access(NATIVE, os.X_OK):
            raise RuntimeError(f"Native camera worker missing or not executable: {NATIVE}")
        if not (SOURCE / "build").is_dir():
            raise RuntimeError(f"Isolated libcamera build missing: {SOURCE}")
        self.proc = await asyncio.create_subprocess_exec(
            "meson", "devenv", "-C", str(SOURCE / "build"),
            str(NATIVE), str(INTERVAL_MS),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=None,
        )
        ready = (await asyncio.wait_for(self.proc.stdout.readline(), timeout=30)).decode().strip()
        if ready != f"READY {WIDTH} {HEIGHT}":
            raise RuntimeError(f"Camera worker did not initialize: {ready[:180]}")
        print(f"[CAMERA WORKER] ready pid={self.proc.pid} interval_ms={INTERVAL_MS} "
              f"mode=on_demand_plus_low_rate", flush=True)

    async def capture_jpeg(self):
        async with self.lock:
            if self.proc is None or self.proc.returncode is not None:
                raise RuntimeError("Native camera process unavailable")
            started = time.perf_counter()
            fd, path = tempfile.mkstemp(prefix="jarvis-frame-", suffix=".rgb")
            os.close(fd)
            try:
                self.proc.stdin.write(("CAPTURE " + path + "\n").encode())
                await self.proc.stdin.drain()
                response = (await asyncio.wait_for(
                    self.proc.stdout.readline(), timeout=12)).decode().strip()
                if not response.startswith("OK "):
                    raise RuntimeError("Native capture failure: " + response[:180])
                import cv2
                import numpy as np
                frame = Path(path).read_bytes()
                if len(frame) != WIDTH * HEIGHT * 3:
                    raise RuntimeError("Unexpected raw camera frame size")
                image = np.frombuffer(frame, dtype=np.uint8).reshape((HEIGHT, WIDTH, 3))
                ok, encoded = cv2.imencode(".jpg", image,
                                         [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not ok or len(encoded) > MAX_JPEG:
                    raise RuntimeError("JPEG encoding failed or exceeded size limit")
                self.captures += 1
                print(f"[CAMERA WORKER] capture={self.captures} duration="
                      f"{time.perf_counter()-started:.3f}s native_s={response[3:]} "
                      f"jpeg_bytes={len(encoded)}", flush=True)
                return encoded.tobytes()
            finally:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(path)

    async def handle_client(self, reader, writer):
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=5)
            if len(raw) > 1024:
                raise ValueError("Request too large")
            request = json.loads(raw)
            if request.get("command") == "status":
                data = {"ok": True, "uptime_seconds": round(time.monotonic()-self.started, 1),
                        "captures": self.captures, "native": process_stats(self.proc.pid)}
            elif request == {"command": "capture"}:
                jpeg = await self.capture_jpeg()
                data = {"ok": True, "jpeg_base64": base64.b64encode(jpeg).decode("ascii")}
            else:
                raise ValueError("Unknown camera command")
        except (OSError, ValueError, RuntimeError, asyncio.TimeoutError) as exc:
            data = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:180]}"}
        try:
            writer.write(json.dumps(data, separators=(",", ":")).encode() + b"\n")
            await asyncio.wait_for(writer.drain(), timeout=10)
        finally:
            writer.close()
            await writer.wait_closed()

    async def report_resources(self):
        previous_cpu = None
        previous_at = time.monotonic()
        while True:
            await asyncio.sleep(60)
            now = time.monotonic()
            stats = process_stats(self.proc.pid)
            cpu = stats.get("cpu_seconds")
            cpu_pct = (100 * (cpu-previous_cpu) / (now-previous_at)
                       if previous_cpu is not None and isinstance(cpu, float) else None)
            print(f"[CAMERA WORKER] resources native_pid={self.proc.pid} "
                  f"cpu_pct_1core={round(cpu_pct, 2) if cpu_pct is not None else 'warming'} "
                  f"rss_mib={stats.get('rss_mib')} processes={stats.get('processes')} "
                  f"threads={stats.get('threads')} captures={self.captures}",
                  flush=True)
            previous_cpu, previous_at = cpu, now

    async def serve(self):
        if not 500 <= INTERVAL_MS <= 60000:
            raise ValueError("Camera interval out of bounds (0.5-60 seconds)")
        await self.start()
        SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()
        try:
            server = await asyncio.start_unix_server(
                self.handle_client, path=str(SOCKET_PATH), limit=1024 * 1024)
            os.chmod(SOCKET_PATH, 0o600)
            async with server:
                reporter = asyncio.create_task(self.report_resources())
                try:
                    # Fail and restart service if native camera exits.
                    await self.proc.wait()
                    raise RuntimeError("Native camera exited unexpectedly")
                finally:
                    reporter.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await reporter
        finally:
            with contextlib.suppress(FileNotFoundError):
                SOCKET_PATH.unlink()
            if self.proc and self.proc.returncode is None:
                self.proc.terminate()
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=3)
                except asyncio.TimeoutError:
                    self.proc.kill()
                    await self.proc.wait()


if __name__ == "__main__":
    asyncio.run(CameraWorker().serve())
