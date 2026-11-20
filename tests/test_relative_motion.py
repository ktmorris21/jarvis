"""Pure, hardware-free guards for conversational relative motion."""
import math
import pytest

pytest.importorskip("rclpy")
pytest.importorskip("nav2_msgs")
pytest.importorskip("tf2_ros")

from body_services.picar.relative_motion import validate_move, footprint_corridor_clear


def test_relative_distance_bounds_and_type():
    assert validate_move({"direction": "forward", "distance_m": 0.3048}) == ("forward", 0.3048)
    assert validate_move({"direction": "backward", "distance_m": 0.1524}) == ("backward", 0.1524)
    for invalid in (
        {"direction": "left", "distance_m": 0.3},
        {"direction": "forward", "distance_m": True},
        {"direction": "forward", "distance_m": float("nan")},
        {"direction": "forward", "distance_m": float("inf")},
        {"direction": "forward", "distance_m": -0.3},
        {"direction": "forward", "distance_m": 2.0},
        {"direction": "forward", "distance_m": 0.03},
        {"direction": "forward", "distance_m": 0.3, "override_safety": True},
    ):
        with pytest.raises(ValueError):
            validate_move(invalid)


class Dummy:
    pass


def grid():
    g = Dummy()
    g.header = Dummy()
    g.header.frame_id = "map"
    g.info = Dummy()
    g.info.width = 80
    g.info.height = 80
    g.info.resolution = 0.05
    g.info.origin = Dummy()
    g.info.origin.position = Dummy()
    g.info.origin.position.x = -2.0
    g.info.origin.position.y = -2.0
    g.info.origin.orientation = Dummy()
    g.info.origin.orientation.x = 0.0
    g.info.origin.orientation.y = 0.0
    g.info.origin.orientation.z = 0.0
    g.info.origin.orientation.w = 1.0
    g.data = [0] * (80 * 80)
    return g


def put(g, x, y, value):
    gx = math.floor((x + 2)/g.info.resolution)
    gy = math.floor((y + 2)/g.info.resolution)
    g.data[gy * g.info.width + gx] = value


def test_clear_and_blocked_corridors():
    g = grid()
    assert footprint_corridor_clear(g, 0, 0, 0, 0.5)[0]
    put(g, 0.48, 0, 100)
    clear, message = footprint_corridor_clear(g, 0, 0, 0, 0.5)
    assert not clear and "Obstacle" in message
    put(g, 0.48, 0, -1)
    clear, message = footprint_corridor_clear(g, 0, 0, 0, 0.5)
    assert not clear and "unknown" in message


def test_backward_clearance_includes_rear_overhang():
    g = grid()
    put(g, -0.31, 0, 100)
    assert not footprint_corridor_clear(g, 0, 0, 0, -0.25)[0]
    assert footprint_corridor_clear(g, 0, 0, 0, 0.25)[0]


def test_unknown_and_out_of_bounds_fail_closed():
    g = grid()
    put(g, 0, 0, -1)
    assert not footprint_corridor_clear(g, 0, 0, 0, 0.2)[0]
    assert not footprint_corridor_clear(g, 1.9, 0, 0, 0.5)[0]
