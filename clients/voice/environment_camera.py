"""Capture a small, stationary two-view JPEG survey from the Pi camera.

Camera pan is owned by the existing head-expressions process. Never
instantiate Picarx (doing so can reset the steering calibration).
"""
import asyncio
import base64
import shutil
import os
import time
import json
from pathlib import Path


WORKER_SOCKET = Path(os.environ.get(
    "JARVIS_CAMERA_WORKER_SOCKET", "/run/jarvis-camera/camera.sock"))


async def _worker_jpeg():
    """Ask the persistent same-user camera service for a fresh post-pan frame."""
    reader, writer = await asyncio.wait_for(
        asyncio.open_unix_connection(str(WORKER_SOCKET), limit=2_250_000),
        timeout=2,
    )
    try:
        writer.write((json.dumps({"command": "capture"}) + "\n").encode())
        await writer.drain()
        raw = await asyncio.wait_for(reader.readline(), timeout=12)
        if not raw or len(raw) > 2_200_000:
            raise RuntimeError("Camera worker returned no or oversized response")
        reply = json.loads(raw)
        if not reply.get("ok"):
            raise RuntimeError("Camera worker: " + str(reply.get("error", "unknown error"))[:200])
        encoded = reply.get("jpeg_base64")
        if not isinstance(encoded, str) or len(encoded) > 2_100_000:
            raise RuntimeError("Camera worker returned invalid image")
        image = base64.b64decode(encoded, validate=True)
        if not image.startswith(bytes.fromhex("ffd8")) or len(image) > 1_500_000:
            raise RuntimeError("Camera worker returned invalid JPEG")
        return image
    finally:
        writer.close()
        await writer.wait_closed()


async def capture_environment(head, trace_id=None):
    started = time.perf_counter()
    trace = trace_id or "untraced"
    camera = shutil.which("rpicam-still") or shutil.which("libcamera-still")
    v4l2_device = int(os.getenv("JARVIS_CAMERA_DEVICE", "0"))
    fallback = Path(__file__).with_name("capture_v4l2.py")
    isolated = Path(__file__).with_name("capture_libcamera.py")
    isolated_cam = Path(os.getenv("JARVIS_LIBCAMERA_SOURCE", "/home/shadowfax/src/libcamera-0.3")) / "build/src/apps/cam/cam"
    images = []
    worker_enabled = WORKER_SOCKET.is_socket()
    print(f"[VISION PROFILE] trace={trace} stage=setup camera_backend="
          f"{'persistent_worker' if worker_enabled else ('isolated_libcamera' if isolated_cam.is_file() else ('rpicam_cli' if camera else 'v4l2'))} "
          f"elapsed={time.perf_counter()-started:.3f}s", flush=True)
    try:
        for label, state in (("left", "scan_left"), ("right", "scan_right")):
            if head.proc is None or head.proc.returncode is not None:
                raise RuntimeError("Camera head controller unavailable")
            move_start = time.perf_counter()
            await head.set(state)
            await asyncio.sleep(0.65)  # allow servo and camera to settle
            print(f"[VISION PROFILE] trace={trace} view={label} stage=pan_settle "
                  f"duration={time.perf_counter()-move_start:.3f}s", flush=True)
            if worker_enabled:
                capture_start = time.perf_counter()
                raw = await _worker_jpeg()
                print(f"[VISION PROFILE] trace={trace} view={label} stage=camera_capture "
                      f"duration={time.perf_counter()-capture_start:.3f}s bytes={len(raw)} "
                      f"exit_code=0 backend=persistent_worker", flush=True)
            else:
                if isolated_cam.is_file():
                    command = ["/usr/bin/python3", str(isolated)]
                elif camera:
                    command = [camera, "--nopreview", "--timeout", "750",
                               "--width", "1280", "--height", "960",
                               "--encoding", "jpg", "--quality", "80", "--output", "-"]
                else:
                    command = ["/usr/bin/python3", str(fallback), "--device", str(v4l2_device)]
                capture_start = time.perf_counter()
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
                print(f"[VISION PROFILE] trace={trace} view={label} stage=camera_capture "
                      f"duration={time.perf_counter()-capture_start:.3f}s bytes={len(raw)} "
                      f"exit_code={proc.returncode}", flush=True)
                if proc.returncode != 0 or not raw.startswith(bytes.fromhex("ffd8")):
                    reason = stderr.decode(errors="replace")[-350:]
                    raise RuntimeError("Camera capture failed: " + reason)
                if len(raw) > 1_500_000:
                    raise RuntimeError("Camera JPEG exceeds 1.5 MB limit")
            encode_start = time.perf_counter()
            encoded = base64.b64encode(raw).decode("ascii")
            images.append({"view": label, "jpeg_base64": encoded})
            print(f"[VISION PROFILE] trace={trace} view={label} stage=base64 "
                  f"duration={time.perf_counter()-encode_start:.3f}s chars={len(encoded)}",
                  flush=True)
        return images
    finally:
        reset_start = time.perf_counter()
        await head.set("idle")
        print(f"[VISION PROFILE] trace={trace} stage=head_reset "
              f"duration={time.perf_counter()-reset_start:.3f}s "
              f"total={time.perf_counter()-started:.3f}s views={len(images)}",
              flush=True)
