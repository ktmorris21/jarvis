#!/usr/bin/env python3
"""Export Jarvis's YOLO nano detector for NCNN inference (manual Pi diagnostic)."""
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", default="yolo26n.pt")
    parser.add_argument("--imgsz", type=int, default=320)
    args = parser.parse_args()
    if args.imgsz < 128 or args.imgsz % 32:
        parser.error("--imgsz must be >=128 and a multiple of 32")
    from ultralytics import YOLO
    exported = Path(YOLO(args.weights).export(format="ncnn", imgsz=args.imgsz))
    if not exported.is_dir():
        raise RuntimeError(f"Expected NCNN model directory: {exported}")
    print(f"NCNN model directory: {exported.resolve()}")
    print(f"Run: python ops/vision_object_detector.py --model {exported} --imgsz {args.imgsz}")

if __name__ == "__main__":
    main()
