"""Dry-run Ackermann /cmd_vel interpreter for Jarvis PiCar-X.

No PiCar-X or robot_hat imports. This node NEVER commands hardware.
Run: /usr/bin/python3 -m body_services.picar.ros_drive_dry_run
"""
import math
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node


class DriveDryRun(Node):
    def __init__(self):
        super().__init__("jarvis_drive_dry_run")
        self.declare_parameter("wheelbase_m", 0.135)
        self.declare_parameter("max_steering_deg", 30.0)
        self.declare_parameter("max_linear_mps", 0.12)
        self.declare_parameter("cmd_timeout_s", 0.5)
        self.declare_parameter("min_turn_speed_mps", 0.005)
        self.last_command = None
        self.timed_out = False
        self.create_subscription(Twist, "/cmd_vel", self.on_cmd, 10)
        self.create_timer(0.1, self.on_watchdog)
        self.get_logger().info("DRY RUN ONLY: no hardware access; listening on /cmd_vel")

    def on_cmd(self, msg):
        v = float(msg.linear.x)
        omega = float(msg.angular.z)
        self.last_command = time.monotonic()
        self.timed_out = False
        if not math.isfinite(v) or not math.isfinite(omega):
            self.get_logger().warning("Rejected nonfinite velocity command")
            return
        if any(abs(x) > 1e-8 for x in (
            msg.linear.y, msg.linear.z, msg.angular.x, msg.angular.y
        )):
            self.get_logger().warning("Rejected unsupported lateral/3D velocity")
            return
        max_v = float(self.get_parameter("max_linear_mps").value)
        wheelbase = float(self.get_parameter("wheelbase_m").value)
        max_delta = float(self.get_parameter("max_steering_deg").value)
        min_turn_v = float(self.get_parameter("min_turn_speed_mps").value)
        if max_v <= 0 or wheelbase <= 0 or not (0 < max_delta <= 45):
            self.get_logger().error("Invalid controller configuration")
            return
        if abs(v) < min_turn_v and abs(omega) > 1e-6:
            self.get_logger().warning("Rejected rotate-in-place command (Ackermann)")
            return
        clipped_v = max(-max_v, min(max_v, v))
        if abs(clipped_v) < 1e-6:
            self.get_logger().info("DRY RUN: STOP")
            return
        # Use original curvature omega/v so a velocity clamp does not alter the path.
        delta = math.degrees(math.atan(wheelbase * omega / v))
        clipped_delta = max(-max_delta, min(max_delta, delta))
        self.get_logger().info(
            f"DRY RUN: v={clipped_v:+.3f} m/s, omega={omega:+.3f} rad/s,"
            f" steering={clipped_delta:+.1f} deg"
            + (" (steering limited)" if clipped_delta != delta else "")
        )

    def on_watchdog(self):
        if self.last_command is None or self.timed_out:
            return
        timeout = float(self.get_parameter("cmd_timeout_s").value)
        if timeout <= 0:
            self.get_logger().error("Watchdog timeout must be positive")
            self.timed_out = True
            return
        if time.monotonic() - self.last_command > timeout:
            self.timed_out = True
            self.get_logger().warning("DRY RUN: watchdog STOP (command stream expired)")


def main():
    rclpy.init()
    node = DriveDryRun()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
