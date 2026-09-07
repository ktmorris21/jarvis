import asyncio


class AbilityError(ValueError):
    pass


class PiCarAbilities:
    def __init__(self, hardware, audio_io=None, obstacle_provider=None):
        self.hardware = hardware
        self.audio_io = audio_io
        self.obstacle_provider = obstacle_provider
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

    async def _obstacle_veto(self, direction):
        """Future seam for LiDAR/local obstacle protection.

        No obstacle provider is configured in the current hardware state, so
        movement is permitted subject only to the existing body speed/time limits.
        """
        if direction != "forward" or self.obstacle_provider is None:
            return None

        try:
            result = await self.obstacle_provider.forward_blocked()
        except Exception as exc:
            return {
                "blocked": True,
                "reason": "obstacle_provider_error",
                "detail": type(exc).__name__,
            }

        return result

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
            veto = await self._obstacle_veto(direction)
            if veto and veto.get("blocked"):
                self.hardware.stop()
                return {
                    "direction": direction,
                    "stopped": True,
                    "stop_reason": veto.get("reason", "obstacle_blocked"),
                    "detail": veto.get("detail"),
                }

            steering = self.hardware.set_steering(requested_steering)
            speed = self.hardware.drive(direction, requested_speed)
            started = asyncio.get_running_loop().time()

            try:
                await asyncio.sleep(duration_ms / 1000.0)
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
            "stop_reason": "duration_complete",
            "bounded_by_body": (
                speed != requested_speed
                or duration_ms != requested_ms
                or steering != requested_steering
            ),
        }
