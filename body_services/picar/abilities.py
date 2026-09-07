import asyncio


class AbilityError(ValueError):
    pass


class PiCarAbilities:
    def __init__(self, hardware, audio_io=None, collision_distance_cm=22.0):
        self.hardware = hardware
        self.audio_io = audio_io
        self.collision_distance_cm = float(collision_distance_cm)
        self._lock = asyncio.Lock()

    async def execute(self, ability, data):
        if ability == "stop":
            self.hardware.stop()
            return {"stopped": True}

        if ability == "speaker":
            if not self.audio_io:
                raise AbilityError("audio output is not configured")
            encoded = data.get("audio_wav_base64")
            if not encoded:
                raise AbilityError("speaker command missing audio_wav_base64")
            await self.audio_io.play_wav_base64(encoded)
            return {"played": True, "text": data.get("text")}

        if ability == "look":
            pan, tilt = self.hardware.look(
                data.get("pan_deg", 0),
                data.get("tilt_deg", 0),
            )
            return {"pan_deg": pan, "tilt_deg": tilt}

        if ability == "look_around":
            return await self.look_around(data)

        if ability == "move":
            return await self.move(data)

        raise AbilityError(f"Unsupported ability: {ability}")

    async def look_around(self, data):
        """Small head sweep ending centered."""
        amplitude = max(5, min(35, abs(int(data.get("amplitude_deg", 28)))))
        pause_s = max(0.10, min(1.0, int(data.get("pause_ms", 350)) / 1000.0))

        sequence = [-amplitude, amplitude, 0]
        for pan in sequence:
            self.hardware.look(pan, 0)
            await asyncio.sleep(pause_s)

        return {
            "completed": True,
            "pan_sequence": sequence,
        }

    async def move(self, data):
        direction = str(data.get("direction", "")).lower()
        if direction not in {"forward", "backward"}:
            raise AbilityError("move.direction must be forward or backward")

        try:
            requested_ms = int(data.get("duration_ms", 0))
            requested_speed = int(data.get("speed", 20))
            requested_steering = int(data.get("steering_deg", 0))
        except (TypeError, ValueError) as exc:
            raise AbilityError("move parameters must be numeric") from exc

        if requested_ms <= 0:
            raise AbilityError("move.duration_ms is required and must be > 0")

        duration_ms = min(requested_ms, self.hardware.limits.max_move_ms)

        async with self._lock:
            # Local edge veto before forward movement.
            if direction == "forward":
                initial_distance = self.hardware.distance_cm()
                if initial_distance is None:
                    self.hardware.stop()
                    return {
                        "direction": direction,
                        "stopped": True,
                        "stop_reason": "ultrasonic_unavailable",
                        "distance_cm": None,
                        "collision_distance_cm": self.collision_distance_cm,
                    }
                if initial_distance < self.collision_distance_cm:
                    self.hardware.stop()
                    return {
                        "direction": direction,
                        "stopped": True,
                        "stop_reason": "obstacle_too_close",
                        "distance_cm": round(initial_distance, 1),
                        "collision_distance_cm": self.collision_distance_cm,
                    }

            steering = self.hardware.set_steering(requested_steering)
            speed = self.hardware.drive(direction, requested_speed)
            started = asyncio.get_running_loop().time()
            stop_reason = "duration_complete"
            last_distance = None

            try:
                while True:
                    elapsed_ms = (
                        asyncio.get_running_loop().time() - started
                    ) * 1000.0
                    if elapsed_ms >= duration_ms:
                        break

                    if direction == "forward":
                        last_distance = self.hardware.distance_cm()
                        if last_distance is None:
                            stop_reason = "ultrasonic_unavailable"
                            break
                        if last_distance < self.collision_distance_cm:
                            stop_reason = "obstacle_too_close"
                            break

                    await asyncio.sleep(0.05)
            finally:
                self.hardware.stop()

            actual_ms = min(
                duration_ms,
                int((asyncio.get_running_loop().time() - started) * 1000),
            )

        return {
            "direction": direction,
            "speed": speed,
            "duration_ms": actual_ms,
            "steering_deg": steering,
            "stop_reason": stop_reason,
            "distance_cm": (
                round(last_distance, 1)
                if last_distance is not None
                else None
            ),
            "collision_distance_cm": self.collision_distance_cm,
            "bounded_by_body": (
                speed != requested_speed
                or duration_ms != requested_ms
                or steering != requested_steering
                or stop_reason != "duration_complete"
            ),
        }
