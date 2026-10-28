#!/usr/bin/python3
"""Capture one JPEG using the isolated libcamera 0.3 build on Ubuntu 24.04.

The distro libcamera 0.2 IPA crashes for OV5647; do not mix these libraries.
Writes JPEG bytes to stdout only. All diagnostics go to stderr.
"""
import argparse
import glob
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=os.environ.get(
        "JARVIS_LIBCAMERA_SOURCE", "/home/shadowfax/src/libcamera-0.3"))
    args = parser.parse_args()
    source = Path(args.source).expanduser().resolve()
    build = source / "build"
    cam = build / "src/apps/cam/cam"
    if not cam.is_file():
        raise RuntimeError(f"Missing built libcamera cam executable: {cam}")
    import cv2
    import numpy as np
    with tempfile.TemporaryDirectory(prefix="jarvis-camera-") as folder:
        pattern = str(Path(folder) / "frame-#.bin")
        command = [
            "meson", "devenv", "-C", str(build), str(cam),
            "-c", "1", "--capture=5",
            "--stream", "role=still,width=1280,height=960,pixelformat=RGB888",
            "--file=" + pattern,
        ]
        subprocess.run(command, check=True, timeout=20, stdout=sys.stderr,
                       stderr=sys.stderr)
        frames = sorted(glob.glob(str(Path(folder) / "frame-*.bin")))
        if not frames:
            raise RuntimeError("libcamera captured no frames")
        raw = Path(frames[-1]).read_bytes()
        if len(raw) != 1280 * 960 * 3:
            raise RuntimeError(f"Unexpected RGB888 frame size: {len(raw)}")
        frame = np.frombuffer(raw, dtype=np.uint8).reshape((960, 1280, 3))
        # Same imwrite/imencode channel interpretation as the user's verified JPEG.
        ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            raise RuntimeError("Unable to encode camera image as JPEG")
        sys.stdout.buffer.write(jpeg.tobytes())


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"libcamera capture error: {exc}", file=sys.stderr)
        sys.exit(1)
