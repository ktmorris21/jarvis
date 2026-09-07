from __future__ import annotations

import asyncio
import os
import shutil
import tempfile


class CameraIO:
    def __init__(self, width: int = 640, height: int = 480):
        self.width = width
        self.height = height
        self.command = self._find_camera_command()

    @staticmethod
    def _find_camera_command() -> str:
        # Newer Raspberry Pi OS uses rpicam-still; older images use libcamera-still.
        for cmd in ("rpicam-still", "libcamera-still"):
            if shutil.which(cmd):
                return cmd
        raise RuntimeError(
            "Neither rpicam-still nor libcamera-still was found. "
            "Verify the Raspberry Pi camera stack is installed."
        )

    async def capture_jpeg(self) -> bytes:
        fd, path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        try:
            proc = await asyncio.create_subprocess_exec(
                self.command,
                "-n",
                "--width", str(self.width),
                "--height", str(self.height),
                "-o", path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                detail = stderr.decode(errors="replace").strip()
                raise RuntimeError(f"{self.command} failed: {detail}")
            with open(path, "rb") as f:
                return f.read()
        finally:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
