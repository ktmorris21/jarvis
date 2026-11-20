"""Async owner of a prewarmed Pi-local ROS stop client subprocess.

Only the worker imports rclpy (using the ROS system Python), so the Vosk/voice
virtual environment needs no ROS Python packages. No per-command ros2 CLI.
"""
import asyncio
import json
import time
from pathlib import Path

WORKER = str(Path(__file__).with_name("ros_stop_worker.py"))
STARTUP_TIMEOUT = 14.0
STOP_TIMEOUT = 3.0


class PersistentStopClient:
    def __init__(self):
        self.process = None
        self.lock = asyncio.Lock()

    async def start(self):
        async with self.lock:
            await self._start_locked()

    async def _start_locked(self):
        if self.process is not None and self.process.returncode is None:
            return
        # Source the ROS environment exactly once per voice service launch.
        # Never interpolate microphone text into this fixed command.
        command = ("source /opt/ros/jazzy/setup.bash && "
                   "source /home/shadowfax/ros2_ws/install/setup.bash && "
                   "exec /usr/bin/python3 -u " + WORKER)
        self.process = await asyncio.create_subprocess_exec(
            "/bin/bash", "-c", command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE)
        try:
            line = await asyncio.wait_for(self.process.stdout.readline(),
                                          timeout=STARTUP_TIMEOUT)
            reply = json.loads(line.decode()) if line else {}
            if reply.get("type") != "ready":
                raise RuntimeError("ROS stop client not ready: " +
                                   str(reply.get("reason", "worker exited")))
            print("[LOCAL STOP] persistent ROS client ready", flush=True)
        except (Exception, asyncio.CancelledError):
            await self._close_locked()
            raise

    async def stop(self):
        async with self.lock:
            if self.process is None or self.process.returncode is not None:
                # Recovery after startup/service failure; normal path is warm.
                print("[LOCAL STOP] restarting unavailable worker", flush=True)
                await self._start_locked()
            start = time.monotonic()
            print("[LOCAL STOP] dispatching ROS stop", flush=True)
            try:
                self.process.stdin.write(b"STOP\n")
                await asyncio.wait_for(self.process.stdin.drain(), timeout=STOP_TIMEOUT)
                line = await asyncio.wait_for(
                    self.process.stdout.readline(), timeout=STOP_TIMEOUT)
                reply = json.loads(line.decode()) if line else {}
                if reply.get("type") != "result" or reply.get("success") is not True:
                    raise RuntimeError("ROS stop rejected: " +
                                       str(reply.get("reason", "worker unavailable")))
                print("[LOCAL STOP] acknowledged elapsed_ms=%d ros_ms=%s" %
                      (round((time.monotonic()-start)*1000),
                       reply.get("elapsed_ms", "unknown")), flush=True)
            except (Exception, asyncio.CancelledError) as exc:
                print("[LOCAL STOP] failed elapsed_ms=%d reason=%s" %
                      (round((time.monotonic()-start)*1000),
                       type(exc).__name__), flush=True)
                # Never risk interpreting a late response as a fresh stop.
                await self._close_locked()
                raise

    async def _close_locked(self):
        process, self.process = self.process, None
        if process is None:
            return
        if process.returncode is None:
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    async def close(self):
        async with self.lock:
            await self._close_locked()
