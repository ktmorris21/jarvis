from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Limits:
    max_speed: int = 35
    max_move_ms: int = 1000
    max_steering_deg: int = 30
    max_pan_deg: int = 35
    max_tilt_deg: int = 35


class PiCarHardware:
    """SunFounder-specific code lives only here."""

    def __init__(self, mock: bool = False):
        self.mock = mock
        self.limits = Limits()
        self._px = None
        if not mock:
            from picarx import Picarx
            self._px = Picarx()

    @staticmethod
    def _clamp(value: int | float, low: int, high: int):
        return max(low, min(high, value))

    def stop(self) -> None:
        if self.mock:
            print("[MOCK HARDWARE] stop")
            return
        self._px.stop()
        self._px.set_dir_servo_angle(0)

    def set_steering(self, degrees: int | float) -> int:
        angle = int(self._clamp(degrees, -self.limits.max_steering_deg, self.limits.max_steering_deg))
        if self.mock:
            print(f"[MOCK HARDWARE] steering={angle}")
        else:
            self._px.set_dir_servo_angle(angle)
        return angle

    def drive(self, direction: str, speed: int | float) -> int:
        bounded_speed = int(self._clamp(speed, 0, self.limits.max_speed))
        if self.mock:
            print(f"[MOCK HARDWARE] {direction} speed={bounded_speed}")
            return bounded_speed

        if direction == "forward":
            self._px.forward(bounded_speed)
        elif direction == "backward":
            self._px.backward(bounded_speed)
        else:
            raise ValueError("direction must be 'forward' or 'backward'")
        return bounded_speed

    def look(self, pan_deg: int | float, tilt_deg: int | float) -> tuple[int, int]:
        pan = int(self._clamp(pan_deg, -self.limits.max_pan_deg, self.limits.max_pan_deg))
        tilt = int(self._clamp(tilt_deg, -self.limits.max_tilt_deg, self.limits.max_tilt_deg))
        if self.mock:
            print(f"[MOCK HARDWARE] look pan={pan} tilt={tilt}")
        else:
            self._px.set_cam_pan_angle(pan)
            self._px.set_cam_tilt_angle(tilt)
        return pan, tilt
