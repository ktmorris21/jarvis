"""Bounded ROS velocity publisher for supervised PiCar-X speed calibration.

Startup/discovery time is excluded from the timed publishing interval.
Motor-on time is approximate; the robot has no motor feedback yet.
Usage (wheels initially elevated for validation):
  /usr/bin/python3 -m body_services.picar.calibrate_drive --duration 4
"""
import argparse
import math
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node


def main():
    p = argparse.ArgumentParser(description="Timed straight-line ROS calibration command")
    p.add_argument("--duration", type=float, default=4.0, help="Publish interval in seconds (max 5)")
    p.add_argument("--speed", type=float, default=0.03, help="Forward requested speed m/s (max 0.03)")
    args = p.parse_args()
    if not (math.isfinite(args.duration) and 0 < args.duration <= 5.0):
        p.error("duration must be between 0 and 5 seconds")
    if not (math.isfinite(args.speed) and 0 < args.speed <= 0.03):
        p.error("speed must be greater than zero and at most 0.03 m/s")

    rclpy.init()
    node = Node("jarvis_timed_drive_calibration")
    pub = node.create_publisher(Twist, "/cmd_vel", 10)
    forward = Twist()
    forward.linear.x = args.speed
    stop = Twist()
    sent = 0
    try:
        print("Waiting up to 15 seconds for /cmd_vel subscriber (motors not commanded)...", flush=True)
        connect_deadline = time.monotonic() + 15.0
        while pub.get_subscription_count() < 1:
            if time.monotonic() >= connect_deadline:
                raise RuntimeError("No /cmd_vel subscriber found; no motion commanded")
            rclpy.spin_once(node, timeout_sec=0.05)
            time.sleep(0.05)
        print(f"Connected. Publishing {args.speed:.3f} m/s for {args.duration:.2f} s.", flush=True)
        begin = time.monotonic()
        deadline = begin + args.duration
        while True:
            now = time.monotonic()
            if now >= deadline:
                break
            pub.publish(forward)
            sent += 1
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        print(f"Publishing STOP after {time.monotonic()-begin:.2f} s ({sent} commands).", flush=True)
    finally:
        # In addition to the drive controller's own 0.5-second watchdog.
        try:
            for _ in range(5):
                pub.publish(stop)
                time.sleep(0.05)
        finally:
            node.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    main()
