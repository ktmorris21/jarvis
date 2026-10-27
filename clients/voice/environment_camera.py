"""Capture a small, stationary three-view JPEG survey from the Pi camera.

Camera pan is owned by the existing head-expressions process. Never
instantiate Picarx (doing so can reset the steering calibration).
"""
import asyncio
import base64
import shutil


async def capture_environment(head):
    camera = shutil.which("rpicam-still") or shutil.which("libcamera-still")
    if not camera:
        raise RuntimeError("Neither rpicam-still nor libcamera-still was found")
    images = []
    try:
        for label, state in (("left", "scan_left"), ("center", "scan_center"),
                             ("right", "scan_right")):
            if head.proc is None or head.proc.returncode is not None:
                raise RuntimeError("Camera head controller unavailable")
            await head.set(state)
            await asyncio.sleep(0.65)  # allow servo and camera to settle
            proc = await asyncio.create_subprocess_exec(
                camera, "--nopreview", "--timeout", "750",
                "--width", "1280", "--height", "960",
                "--encoding", "jpg", "--quality", "80",
                "--output", "-",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                raw, stderr = await asyncio.wait_for(proc.communicate(), timeout=12)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                raise RuntimeError("Camera capture timed out")
            if proc.returncode != 0 or not raw.startswith(b"\\xff\\xd8"):
                reason = stderr.decode(errors="replace")[-350:]
                raise RuntimeError("Camera capture failed: " + reason)
            if len(raw) > 1_500_000:
                raise RuntimeError("Camera JPEG exceeds 1.5 MB limit")
            images.append({"view": label, "jpeg_base64": base64.b64encode(raw).decode("ascii")})
        return images
    finally:
        await head.set("idle")
