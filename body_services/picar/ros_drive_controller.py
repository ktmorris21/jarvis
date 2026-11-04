"""ROS 2 PiCar-X drive controller with explicit, fail-safe software arming.

By default, this is a hardware-free dry run. Hardware access requires two
explicit startup flags. Hardware mode always starts DISARMED and never
automatically re-arms after a service restart, stop, or watchdog timeout.

ROS interface:
  /cmd_vel               geometry_msgs/msg/Twist
  /jarvis_drive/set_armed std_srvs/srv/SetBool (true=arm; false=disarm)

For supervised floor tests, the operator must remain near the physical power
switch; this software arm is NOT an independent emergency stop or collision
monitor. Restrict ROS-network access to trusted machines.
"""
import argparse
import math
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from std_srvs.srv import SetBool

from .hardware import PiCarHardware


def convert_command(v, omega, wheelbase, max_v, max_steer, min_turn_v):
    """Return (effective_v, steering_degrees) or raise ValueError."""
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
        self.declare_parameter("wheelbase_m", 0.0936625)
        self.declare_parameter("max_linear_mps", 0.12)
        self.declare_parameter("max_steering_deg", 30.0)
        self.declare_parameter("min_turn_speed_mps", 0.005)
        self.declare_parameter("cmd_timeout_s", 0.5)
        self.declare_parameter("max_motor_power", 20)
        self.declare_parameter("steering_sign", -1)
        self.hardware_enabled = hardware_enabled
        self.hw = None
        self.armed = False
        self.armed_at = None
        self.last_valid_at = None
        self.in_motion = False
        self.timed_out = False
        if hardware_enabled:
            self.hw = PiCarHardware(mock=False)
            self.hw.stop()
            self.get_logger().warning("HARDWARE AVAILABLE, DISARMED: no movement until explicitly armed")
        else:
            self.get_logger().info("DRY RUN: hardware not initialized; arming unavailable")
        self.create_subscription(Twist, "/cmd_vel", self.on_command, 10)
        self.create_service(SetBool, "/jarvis_drive/set_armed", self.set_armed)
        self.create_timer(0.05, self.on_watchdog)

    def stop(self, reason):
        if self.hw is not None:
            self.hw.stop()
        if self.in_motion:
            self.get_logger().warning("STOP: " + reason)
        self.in_motion = False

    def disarm(self, reason):
        self.armed = False
        self.armed_at = None
        self.last_valid_at = None
        self.timed_out = True
        self.stop(reason)
        self.get_logger().warning("DISARMED: " + reason)

    def set_armed(self, request, response):
        if not request.data:
            self.disarm("operator request")
            response.success = True
            response.message = "Disarmed; motors stopped"
            return response
        if self.hw is None:
            response.success = False
            response.message = "Hardware unavailable: controller is in dry-run mode"
            return response
        try:
            self.stop("arming reset")
            self.armed = True
            self.armed_at = time.monotonic()
            self.last_valid_at = None
            self.timed_out = False
            self.get_logger().warning("ARMED for supervised testing (30s to first command)")
            response.success = True
            response.message = "Armed; send commands within 30 seconds; zero command disarms"
        except Exception as exc:
            self.disarm("arming failure")
            response.success = False
            response.message = str(exc)
        return response

    def on_command(self, msg):
        # In hardware mode, commands are ignored unless explicitly armed.
        if self.hw is not None and not self.armed:
            return
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
                if self.hw is not None:
                    self.disarm("zero velocity command")
                else:
                    self.stop("zero velocity")
                    self.last_valid_at = None
                return
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
            self.disarm("invalid command or hardware error")
            self.get_logger().error(f"Command rejected: {type(exc).__name__}: {exc}")

    def on_watchdog(self):
        now = time.monotonic()
        if self.hw is not None and self.armed and self.last_valid_at is None:
            if self.armed_at is not None and now - self.armed_at > 30.0:
                self.disarm("no first command within 30 seconds")
            return
        if self.last_valid_at is None or self.timed_out:
            return
        timeout = float(self.get_parameter("cmd_timeout_s").value)
        if not math.isfinite(timeout) or timeout <= 0 or now - self.last_valid_at > timeout:
            self.disarm("command watchdog expired")

    def destroy_node(self):
        try:
            self.disarm("controller shutdown")
        finally:
            return super().destroy_node()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--enable-hardware", action="store_true")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--confirm-wheels-elevated", action="store_true")
    group.add_argument("--confirm-supervised-floor", action="store_true")
    args, ros_args = parser.parse_known_args()
    confirmed = args.confirm_wheels_elevated or args.confirm_supervised_floor
    if args.enable_hardware != confirmed:
        parser.error("Hardware mode requires --enable-hardware and one physical-test confirmation flag")
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
