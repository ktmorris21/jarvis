import asyncio

from body_services.picar.abilities import PiCarAbilities


class FakeHardware:
    class Limits:
        max_move_ms = 1000
        max_speed = 35
        max_steering_deg = 30

    def __init__(self):
        self.limits = self.Limits()
        self.stopped = False
        self.driven = False

    def stop(self):
        self.stopped = True

    def set_steering(self, degrees):
        return max(-30, min(30, int(degrees)))

    def drive(self, direction, speed):
        self.driven = True
        return min(35, int(speed))

    def look(self, pan, tilt):
        return int(pan), int(tilt)


def test_forward_motion_does_not_require_ultrasonic_sensor():
    async def run():
        hw = FakeHardware()
        abilities = PiCarAbilities(hw)
        result = await abilities.move({
            "direction": "forward",
            "speed": 18,
            "duration_ms": 100,
            "steering_deg": 0,
        })
        assert hw.driven is True
        assert hw.stopped is True
        assert result["stop_reason"] == "duration_complete"

    asyncio.run(run())


def test_motion_still_respects_body_bounds():
    async def run():
        hw = FakeHardware()
        abilities = PiCarAbilities(hw)
        result = await abilities.move({
            "direction": "forward",
            "speed": 99,
            "duration_ms": 5000,
            "steering_deg": 99,
        })
        assert result["speed"] == 35
        assert result["duration_ms"] <= 1000
        assert result["steering_deg"] == 30
        assert result["bounded_by_body"] is True

    asyncio.run(run())


class AlwaysBlocked:
    async def forward_blocked(self):
        return {"blocked": True, "reason": "future_lidar_block"}


def test_future_obstacle_provider_can_veto_forward_motion():
    async def run():
        hw = FakeHardware()
        abilities = PiCarAbilities(hw, obstacle_provider=AlwaysBlocked())
        result = await abilities.move({
            "direction": "forward",
            "speed": 18,
            "duration_ms": 200,
            "steering_deg": 0,
        })
        assert hw.driven is False
        assert result["stop_reason"] == "future_lidar_block"

    asyncio.run(run())
