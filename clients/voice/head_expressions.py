#!/usr/bin/python3
"""Camera-only expressive head controller. Commands on stdin: idle, listening, thinking, speaking, scan_left, scan_center, scan_right, quit."""
import select
import sys
from robot_hat import Servo

PAN_CALIBRATION = 0
TILT_CALIBRATION = 0
LISTEN_PAN = 18
THINK_TILT = 15
SPEAK_NODS = (0, 4, 0, -3)
SPEAK_INTERVAL = 0.65

pan = Servo("P0")
tilt = Servo("P1")
state = "idle"
nod_index = 0

def position(pan_deg=0, tilt_deg=0):
    pan_deg = max(-45, min(45, pan_deg))
    tilt_deg = max(-25, min(25, tilt_deg))
    pan.angle(PAN_CALIBRATION - pan_deg)
    tilt.angle(TILT_CALIBRATION - tilt_deg)

def set_state(new_state):
    global state, nod_index
    if new_state not in ("idle", "listening", "thinking", "speaking", "scan_left", "scan_center", "scan_right"):
        print(f"Unknown expression: {new_state}", flush=True)
        return
    state = new_state
    nod_index = 0
    print(f"[HEAD] {state}", flush=True)
    if state == "idle":
        position(0, 0)
    elif state == "listening":
        position(LISTEN_PAN, 0)
    elif state == "thinking":
        position(0, THINK_TILT)
    elif state == "speaking":
        position(0, 0)
    elif state == "scan_left":
        position(-45, 0)
    elif state == "scan_center":
        position(0, 0)
    elif state == "scan_right":
        position(45, 0)

try:
    set_state("idle")
    while True:
        timeout = SPEAK_INTERVAL if state == "speaking" else None
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if ready:
            line = sys.stdin.readline()
            if not line:
                break
            command = line.strip().lower()
            if command == "quit":
                break
            set_state(command)
        elif state == "speaking":
            position(0, SPEAK_NODS[nod_index])
            nod_index = (nod_index + 1) % len(SPEAK_NODS)
finally:
    print("[HEAD] Returning to neutral", flush=True)
    position(0, 0)
