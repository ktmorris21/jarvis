from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass


@dataclass
class SceneMonitorConfig:
    width: int = 160
    height: int = 120
    fps: float = 2.0
    threshold: float = 12.0
    cooldown_seconds: float = 8.0
    sample_stride: int = 4


class SceneMonitor:
    """Very cheap scene-change detector using only the Y plane of YUV420 frames.

    It does not know what changed. It only detects that the camera scene differs
    materially from its current baseline.
    """

    def __init__(self, config: SceneMonitorConfig | None = None):
        self.config = config or SceneMonitorConfig()
        self.command = self._find_video_command()
        self._proc = None
        self._baseline: bytes | None = None

    @staticmethod
    def _find_video_command() -> str:
        for cmd in ("rpicam-vid", "libcamera-vid"):
            if shutil.which(cmd):
                return cmd
        raise RuntimeError(
            "Neither rpicam-vid nor libcamera-vid was found. "
            "Verify the Raspberry Pi camera stack is installed."
        )

    @property
    def y_bytes(self) -> int:
        return self.config.width * self.config.height

    @property
    def frame_bytes(self) -> int:
        # YUV420 = 1.5 bytes per pixel.
        return self.y_bytes * 3 // 2

    async def start(self) -> None:
        if self._proc and self._proc.returncode is None:
            return

        self._proc = await asyncio.create_subprocess_exec(
            self.command,
            "-n",
            "--codec", "yuv420",
            "--width", str(self.config.width),
            "--height", str(self.config.height),
            "--framerate", str(self.config.fps),
            "--timeout", "0",
            "-o", "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._baseline = None

    async def stop(self) -> None:
        proc = self._proc
        self._proc = None
        self._baseline = None
        if not proc:
            return
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

    async def read_y_plane(self) -> bytes:
        if not self._proc or not self._proc.stdout:
            raise RuntimeError("Scene monitor is not running")
        try:
            frame = await self._proc.stdout.readexactly(self.frame_bytes)
        except asyncio.IncompleteReadError as exc:
            detail = ""
            if self._proc.stderr:
                try:
                    err = await asyncio.wait_for(self._proc.stderr.read(), timeout=0.2)
                    detail = err.decode(errors="replace").strip()
                except Exception:
                    pass
            raise RuntimeError(
                f"Camera monitor stream ended unexpectedly. {detail}"
            ) from exc
        return frame[: self.y_bytes]

    def difference_score(self, current: bytes, baseline: bytes) -> float:
        """Mean absolute luminance difference after compensating global brightness.

        Global exposure/light shifts are discounted so motion/object changes dominate.
        """
        stride = max(1, self.config.sample_stride)
        cur = current[::stride]
        base = baseline[::stride]
        if not cur or len(cur) != len(base):
            return 0.0

        mean_cur = sum(cur) / len(cur)
        mean_base = sum(base) / len(base)
        global_shift = mean_cur - mean_base

        total = 0.0
        for c, b in zip(cur, base):
            total += abs((c - b) - global_shift)
        return total / len(cur)

    async def wait_for_change(self) -> dict:
        """Block until scene differs from baseline beyond threshold."""
        if not self._proc or self._proc.returncode is not None:
            await self.start()

        if self._baseline is None:
            # Read two frames to let auto-exposure settle a little.
            self._baseline = await self.read_y_plane()
            self._baseline = await self.read_y_plane()

        while True:
            current = await self.read_y_plane()
            score = self.difference_score(current, self._baseline)

            if score >= self.config.threshold:
                # New scene becomes baseline after this trigger.
                self._baseline = current
                return {
                    "score": round(score, 2),
                    "threshold": self.config.threshold,
                }

            # Slowly track ordinary camera drift without following abrupt changes.
            # Byte-wise blend: 95% baseline / 5% current, integer arithmetic.
            self._baseline = bytes(
                ((b * 19 + c) // 20)
                for b, c in zip(self._baseline, current)
            )
