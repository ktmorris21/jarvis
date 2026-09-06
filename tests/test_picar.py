import asyncio

from body_services.picar.abilities import AbilityError, PiCarAbilities
from body_services.picar.hardware import PiCarHardware


def test_body_clamps_look_angles():
    hw = PiCarHardware(mock=True)
    abilities = PiCarAbilities(hw)
    result = asyncio.run(abilities.look({"pan_deg": 100, "tilt_deg": -100}))
    assert result == {"pan_deg": 35, "tilt_deg": -35}


def test_body_bounds_motion():
    hw = PiCarHardware(mock=True)
    abilities = PiCarAbilities(hw)
    result = asyncio.run(abilities.move({
        "direction": "forward",
        "speed": 99,
        "duration_ms": 5000,
        "steering_deg": 80,
    }))
    assert result["speed"] == 35
    assert result["duration_ms"] == 1000
    assert result["steering_deg"] == 30
    assert result["bounded_by_body"] is True


def test_body_rejects_unbounded_move():
    hw = PiCarHardware(mock=True)
    abilities = PiCarAbilities(hw)
    try:
        asyncio.run(abilities.move({"direction": "forward", "speed": 20}))
        assert False, "Expected AbilityError"
    except AbilityError:
        pass
