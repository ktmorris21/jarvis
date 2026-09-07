import asyncio

from body_services.picar.abilities import PiCarAbilities


class FakeHardware:
    class Limits:
        max_move_ms = 1000
        max_speed = 35
        max_steering_deg = 30

    def __init__(self, distances):
        self.limits = self.Limits()
        self.distances = iter(distances)
        self.stopped = False
        self.driven = False

    def distance_cm(self):
        try:
            return next(self.distances)
        except StopIteration:
            return 100.0

    def stop(self):
        self.stopped = True

    def set_steering(self, degrees):
        return max(-30, min(30, int(degrees)))

    def drive(self, direction, speed):
        self.driven = True
        return min(35, int(speed))

    def look(self, pan, tilt):
        return int(pan), int(tilt)


def test_forward_move_vetoed_when_obstacle_close():
    async def run():
        hw = FakeHardware([10.0])
        abilities = PiCarAbilities(hw, collision_distance_cm=22.0)
        result = await abilities.move({
            "direction": "forward",
            "speed": 20,
            "duration_ms": 300,
            "steering_deg": 0,
        })
        assert result["stopped"] is True
        assert result["stop_reason"] == "obstacle_too_close"
        assert hw.driven is False

    asyncio.run(run())


def test_forward_move_stops_if_obstacle_appears():
    async def run():
        hw = FakeHardware([100.0, 100.0, 15.0])
        abilities = PiCarAbilities(hw, collision_distance_cm=22.0)
        result = await abilities.move({
            "direction": "forward",
            "speed": 20,
            "duration_ms": 500,
            "steering_deg": 0,
        })
        assert result["stop_reason"] == "obstacle_too_close"
        assert hw.stopped is True
        assert hw.driven is True

    asyncio.run(run())


def test_backward_motion_does_not_require_front_ultrasonic():
    async def run():
        hw = FakeHardware([])
        abilities = PiCarAbilities(hw, collision_distance_cm=22.0)
        result = await abilities.move({
            "direction": "backward",
            "speed": 15,
            "duration_ms": 100,
            "steering_deg": 0,
        })
        assert result["stop_reason"] == "duration_complete"
        assert hw.driven is True

    asyncio.run(run())
