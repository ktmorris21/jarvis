"""Capture a small, stationary two-view JPEG survey from the Pi camera.

Camera pan is owned by the existing head-expressions process. Never
instantiate Picarx (doing so can reset the steering calibration).
"""
import asyncio
import base64
import shutil
import os
from pathlib import Path


async def capture_environment(head):
    camera = shutil.which("rpicam-still") or shutil.which("libcamera-still")
    v4l2_device = int(os.getenv("JARVIS_CAMERA_DEVICE", "0"))
    fallback = Path(__file__).with_name("capture_v4l2.py")
    isolated = Path(__file__).with_name("capture_libcamera.py")
    isolated_cam = Path(os.getenv("JARVIS_LIBCAMERA_SOURCE", "/home/shadowfax/src/libcamera-0.3")) / "build/src/apps/cam/cam"
    images = []
    try:
        for label, state in (("left", "scan_left"), ("right", "scan_right")):
            if head.proc is None or head.proc.returncode is not None:
                raise RuntimeError("Camera head controller unavailable")
            await head.set(state)
            await asyncio.sleep(0.65)  # allow servo and camera to settle
            if isolated_cam.is_file():
                command = ["/usr/bin/python3", str(isolated)]
            elif camera:
                command = [camera, "--nopreview", "--timeout", "750",
                           "--width", "1280", "--height", "960",
                           "--encoding", "jpg", "--quality", "80", "--output", "-"]
            else:
                command = ["/usr/bin/python3", str(fallback), "--device", str(v4l2_device)]
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                raw, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                raise RuntimeError("Camera capture timed out")
            if proc.returncode != 0 or not raw.startswith(bytes.fromhex("ffd8")):
                reason = stderr.decode(errors="replace")[-350:]
                raise RuntimeError("Camera capture failed: " + reason)
            if len(raw) > 1_500_000:
                raise RuntimeError("Camera JPEG exceeds 1.5 MB limit")
            images.append({"view": label, "jpeg_base64": base64.b64encode(raw).decode("ascii")})
        return images
    finally:
        await head.set("idle")
