#!/usr/bin/python3
"""Emit one JPEG frame from a V4L2 camera to stdout (binary), diagnostics to stderr.

Run under /usr/bin/python3, where Ubuntu's python3-opencv is installed.
This utility does not touch PiCarx, motors, or camera servos.
"""
import argparse
import sys
import time

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=int, default=0)
    args = parser.parse_args()
    import cv2
    capture = cv2.VideoCapture(args.device, cv2.CAP_V4L2)
    try:
        if not capture.isOpened():
            raise RuntimeError(f"Cannot open /dev/video{args.device} using V4L2")
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 960)
        # Allow auto-exposure to settle; retain last successfully read image.
        frame = None
        for _ in range(8):
            ok, candidate = capture.read()
            if ok and candidate is not None and candidate.size:
                frame = candidate
            time.sleep(0.06)
        if frame is None:
            raise RuntimeError(f"No readable frames from /dev/video{args.device}")
        ok, data = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            raise RuntimeError("OpenCV JPEG encoding failed")
        sys.stdout.buffer.write(data.tobytes())
    finally:
        capture.release()

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Camera capture error: {exc}", file=sys.stderr)
        sys.exit(1)
