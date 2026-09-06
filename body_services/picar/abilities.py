from __future__ import annotations

import asyncio
from typing import Any

from .hardware import PiCarHardware


class AbilityError(ValueError):
    pass


class PiCarAbilities:
    def __init__(self, hardware: PiCarHardware):
        self.hardware = hardware
        self._movement_lock = asyncio.Lock()

    async def execute(self, ability: str, data: dict[str, Any]) -> dict[str, Any]:
        if ability == "stop":
            self.hardware.stop()
            return {"stopped": True}
        if ability == "look":
            return await self.look(data)
        if ability == "move":
            return await self.move(data)
        raise AbilityError(f"Unsupported ability: {ability}")

    async def look(self, data: dict[str, Any]) -> dict[str, Any]:
        pan = data.get("pan_deg", 0)
        tilt = data.get("tilt_deg", 0)
        actual_pan, actual_tilt = self.hardware.look(pan, tilt)
        return {"pan_deg": actual_pan, "tilt_deg": actual_tilt}

    async def move(self, data: dict[str, Any]) -> dict[str, Any]:
        direction = str(data.get("direction", "")).lower()
        if direction not in {"forward", "backward"}:
            raise AbilityError("move.direction must be forward or backward")

        try:
            requested_speed = int(data.get("speed", 20))
            requested_ms = int(data.get("duration_ms", 0))
            requested_steering = int(data.get("steering_deg", 0))
        except (TypeError, ValueError) as exc:
            raise AbilityError("speed, duration_ms, and steering_deg must be integers") from exc

        if requested_ms <= 0:
            raise AbilityError("move.duration_ms is required and must be > 0")

        duration_ms = min(requested_ms, self.hardware.limits.max_move_ms)

        async with self._movement_lock:
            steering = self.hardware.set_steering(requested_steering)
            speed = self.hardware.drive(direction, requested_speed)
            try:
                await asyncio.sleep(duration_ms / 1000.0)
            finally:
                self.hardware.stop()

        return {
            "direction": direction,
            "speed": speed,
            "duration_ms": duration_ms,
            "steering_deg": steering,
            "bounded_by_body": (
                speed != requested_speed
                or duration_ms != requested_ms
                or steering != requested_steering
            ),
        }
