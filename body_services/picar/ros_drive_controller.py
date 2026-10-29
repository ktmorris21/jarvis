"""Experimental ROS 2 PiCar-X drive controller.

Default mode is strictly hardware-free. Physical output requires TWO explicit
local command-line flags. Do not run in hardware mode on the floor until a
collision monitor and independent emergency stop are installed.

Run from repository root:
  /usr/bin/python3 -m body_services.picar.ros_drive_controller
"""
import argparse
import math
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node

from .hardware import PiCarHardware


def convert_command(v, omega, wheelbase, max_v, max_steer, min_turn_v):
    """Return (effective_v, steering_degrees) or raise ValueError.

    Geometry assumes positive angular.z means left turn; actual servo polarity
    must be verified on the elevated chassis before floor operation.
    """
    if not all(math.isfinite(x) for x in (v, omega)):
        raise ValueError("nonfinite command")
    if wheelbase <= 0 or max_v <= 0 or not 0 < max_steer <= 45:
        raise ValueError("invalid geometry/limit configuration")
    if abs(v) < min_turn_v:
        if abs(omega) > 1e-6:
            raise ValueError("rotation-in-place unsupported (Ackermann)")
        return 0.0, 0.0
    speed = max(-max_v, min(max_v, v))
    angle = math.degrees(math.atan(wheelbase * omega / v))
    return speed, max(-max_steer, min(max_steer, angle))


class RosDriveController(Node):
    def __init__(self, hardware_enabled=False):
        super().__init__("jarvis_drive_controller")
        self.declare_parameter("wheelbase_m", 0.135)  # measure before floor operation
        self.declare_parameter("max_linear_mps", 0.12)  # provisional; not measured
        self.declare_parameter("max_steering_deg", 30.0)
        self.declare_parameter("min_turn_speed_mps", 0.005)
        self.declare_parameter("cmd_timeout_s", 0.5)
        self.declare_parameter("max_motor_power", 20)  # PiCar-X API units, NOT m/s
        self.declare_parameter("steering_sign", -1)  # measured: negative flips PiCar servo to ROS left-positive
        self.hardware_enabled = hardware_enabled
        self.hw = None
        self.last_valid_at = None
        self.in_motion = False
        self.timed_out = False
        if hardware_enabled:
            # PiCarx constructor touches servos; NEVER construct in dry-run.
            self.hw = PiCarHardware(mock=False)
            self.hw.stop()
            self.get_logger().warning("HARDWARE ENABLED: keep wheels OFF THE GROUND")
        else:
            self.get_logger().info("DRY RUN: hardware not initialized")
        self.create_subscription(Twist, "/cmd_vel", self.on_command, 10)
        self.create_timer(0.05, self.on_watchdog)

    def stop(self, reason):
        if self.hw is not None:
            self.hw.stop()
        if self.in_motion:
            self.get_logger().warning("STOP: " + reason)
        self.in_motion = False

    def on_command(self, msg):
        try:
            extras = (msg.linear.y, msg.linear.z, msg.angular.x, msg.angular.y)
            if any(not math.isfinite(x) or abs(x) > 1e-8 for x in extras):
                raise ValueError("unsupported lateral/3D command")
            v, angle = convert_command(
                float(msg.linear.x), float(msg.angular.z),
                float(self.get_parameter("wheelbase_m").value),
                float(self.get_parameter("max_linear_mps").value),
                float(self.get_parameter("max_steering_deg").value),
                float(self.get_parameter("min_turn_speed_mps").value),
            )
            timeout = float(self.get_parameter("cmd_timeout_s").value)
            max_power = int(self.get_parameter("max_motor_power").value)
            steering_sign = int(self.get_parameter("steering_sign").value)
            if not math.isfinite(timeout) or timeout <= 0 or not 0 < max_power <= 35:
                raise ValueError("invalid watchdog/power configuration")
            if steering_sign not in (-1, 1):
                raise ValueError("steering_sign must be -1 or +1")
            steer_deg = angle * steering_sign
            if abs(v) < 1e-9:
                self.stop("zero velocity")
            else:
                motor_power = max(1, min(max_power, round(abs(v) /
                    float(self.get_parameter("max_linear_mps").value) * max_power)))
                if self.hw is not None:
                    self.hw.set_steering(steer_deg)
                    self.hw.drive("forward" if v > 0 else "backward", motor_power)
                self.in_motion = True
                self.get_logger().info(
                    f"{'HARDWARE' if self.hw else 'DRY RUN'} "
                    f"v={v:+.3f} m/s steer={steer_deg:+.1f}deg "
                    f"power={motor_power}/{max_power}"
                )
            self.last_valid_at = time.monotonic()
            self.timed_out = False
        except Exception as exc:
            self.stop("invalid command or hardware error")
            self.last_valid_at = None
            self.get_logger().error(f"Command rejected: {type(exc).__name__}: {exc}")

    def on_watchdog(self):
        if self.last_valid_at is None or self.timed_out:
            return
        timeout = float(self.get_parameter("cmd_timeout_s").value)
        if not math.isfinite(timeout) or timeout <= 0 or time.monotonic() - self.last_valid_at > timeout:
            self.timed_out = True
            self.stop("watchdog expired")
            self.get_logger().warning("Watchdog triggered")

    def destroy_node(self):
        try:
            self.stop("controller shutdown")
        finally:
            return super().destroy_node()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--enable-hardware", action="store_true")
    parser.add_argument("--confirm-wheels-elevated", action="store_true")
    args, ros_args = parser.parse_known_args()
    if args.enable_hardware != args.confirm_wheels_elevated:
        parser.error("Hardware operation requires BOTH --enable-hardware and --confirm-wheels-elevated")
    rclpy.init(args=ros_args)
    node = None
    try:
        node = RosDriveController(hardware_enabled=args.enable_hardware)
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
