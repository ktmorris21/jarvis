"""Read-only ROS 2 status provider for the existing Jarvis Core protocol.

Run inside a ROS Jazzy Python environment (not Railway). No PiCar/motor imports.
"""
import argparse
import asyncio
import json
import math
import os
import threading
import time
from datetime import datetime, timezone

import rclpy
from geometry_msgs.msg import TransformStamped
from nav_msgs.msg import OccupancyGrid
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data, QoSProfile, ReliabilityPolicy, DurabilityPolicy
from rclpy.time import Time
from sensor_msgs.msg import LaserScan
from tf2_ros import Buffer, TransformListener
import websockets


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def age_seconds(last_time, now=None):
    if last_time is None:
        return None
    return round(max(0.0, (time.monotonic() if now is None else now) - last_time), 3)


def is_fresh(last_time, max_age, now=None):
    age = age_seconds(last_time, now)
    return age is not None and age <= max_age


def heading_degrees(q):
    return round(math.degrees(math.atan2(
        2 * (q.w * q.z + q.x * q.y),
        1 - 2 * (q.y * q.y + q.z * q.z),
    )), 2)


class RosStatusNode(Node):
    def __init__(self, scan_topic="/scan", map_topic="/map", map_frame="map", base_frame="base_link"):
        super().__init__("jarvis_ros_status")
        self.scan_topic = scan_topic
        self.map_topic = map_topic
        self.map_frame = map_frame
        self.base_frame = base_frame
        self.last_scan_at = None
        self.last_map_at = None
        self.last_scan_stamp = None
        self.last_map_stamp = None
        self.map_dimensions = None
        self._lock = threading.Lock()
        map_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                             durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(LaserScan, scan_topic, self._scan_callback, qos_profile_sensor_data)
        self.create_subscription(OccupancyGrid, map_topic, self._map_callback, map_qos)
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

    def _scan_callback(self, msg):
        with self._lock:
            self.last_scan_at = time.monotonic()
            self.last_scan_stamp = {"sec": msg.header.stamp.sec, "nanosec": msg.header.stamp.nanosec}

    def _map_callback(self, msg):
        with self._lock:
            self.last_map_at = time.monotonic()
            self.last_map_stamp = {"sec": msg.header.stamp.sec, "nanosec": msg.header.stamp.nanosec}
            self.map_dimensions = {
                "width": msg.info.width, "height": msg.info.height,
                "resolution_m": round(float(msg.info.resolution), 4),
            }

    def status(self, robot_id, scan_stale_after=2.0, map_stale_after=60.0):
        now = time.monotonic()
        with self._lock:
            last_scan = self.last_scan_at
            last_map = self.last_map_at
            dimensions = dict(self.map_dimensions) if self.map_dimensions else None
        scan_age = age_seconds(last_scan, now)
        map_age = age_seconds(last_map, now)
        pose = {"available": False, "frame": self.map_frame}
        try:
            tf = self.tf_buffer.lookup_transform(self.map_frame, self.base_frame, Time())
            p, q = tf.transform.translation, tf.transform.rotation
            # Reject nonfinite inputs, which cannot be serialized as valid JSON.
            values = [p.x, p.y, q.x, q.y, q.z, q.w]
            if all(math.isfinite(v) for v in values):
                pose = {
                    "available": True, "frame": self.map_frame,
                    "x": round(float(p.x), 3), "y": round(float(p.y), 3),
                    "heading_deg": heading_degrees(q),
                    "transform_stamp": {
                        "sec": tf.header.stamp.sec,
                        "nanosec": tf.header.stamp.nanosec,
                    },
                }
        except Exception:
            pass
        return {
            "robot_id": robot_id,
            "observed_at": utc_now(),
            "ros_connected": bool(rclpy.ok()),
            "lidar": {"active": is_fresh(last_scan, scan_stale_after, now),
                      "last_scan_age_seconds": scan_age},
            "mapping": {"available": last_map is not None,
                        "recent_update": is_fresh(last_map, map_stale_after, now),
                        "last_map_age_seconds": map_age,
                        "dimensions": dimensions},
            "pose": pose,
        }


def ros_spin(node, stop):
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    try:
        while not stop.is_set() and rclpy.ok():
            executor.spin_once(timeout_sec=0.1)
    finally:
        executor.remove_node(node)
        executor.shutdown()


async def bridge_loop(args, node):
    url = args.url.rstrip("/").replace("https://", "wss://").replace("http://", "ws://")
    url += "/ws?token=" + args.token
    while True:
        try:
            async with websockets.connect(url, max_size=4 * 1024 * 1024) as ws:
                await ws.send(json.dumps({
                    "type": "hello", "interface_id": args.interface_id,
                    "interface_type": "ros_status",
                    "capabilities": ["get_robot_status"],
                }))
                reply = json.loads(await ws.recv())
                if reply.get("type") != "hello_ack":
                    raise RuntimeError("Core rejected bridge hello")
                print("ROS bridge connected to Core", flush=True)
                async for raw in ws:
                    command = json.loads(raw)
                    if command.get("type") != "command":
                        continue
                    ability = command.get("ability")
                    if ability != "get_robot_status":
                        # Never execute other commands, even if Core sends one.
                        result, status, error = None, "failed", "unsupported read-only bridge command"
                    else:
                        try:
                            result = node.status(args.robot_id)
                            status, error = "complete", None
                        except Exception as exc:
                            result, status, error = None, "failed", type(exc).__name__
                    await ws.send(json.dumps({
                        "type": "event", "event": "COMMAND_RESULT", "timestamp": utc_now(),
                        "data": {
                            "command_id": command.get("command_id"),
                            "ability": ability, "status": status,
                            "result": result, "error": error,
                        },
                    }, allow_nan=False))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"ROS bridge disconnected ({type(exc).__name__}); reconnecting", flush=True)
            await asyncio.sleep(3)


def main():
    parser = argparse.ArgumentParser(description="Read-only ROS status bridge for Jarvis Core")
    parser.add_argument("--url", default=os.getenv("JARVIS_URL"), required=False, help="Jarvis Core HTTPS base URL")
    parser.add_argument("--token", default=os.getenv("JARVIS_TOKEN"), required=False, help="Jarvis interface token (prefer JARVIS_TOKEN env var)")
    parser.add_argument("--interface-id", default="picar-ros")
    parser.add_argument("--robot-id", default="picar-main")
    parser.add_argument("--scan-topic", default="/scan")
    parser.add_argument("--map-topic", default="/map")
    parser.add_argument("--map-frame", default="map")
    parser.add_argument("--base-frame", default="base_link")
    args = parser.parse_args()
    if not args.url or not args.token:
        parser.error("Provide URL/token via flags or JARVIS_URL/JARVIS_TOKEN environment variables")
    if not args.url.startswith("https://") and not args.url.startswith("http://localhost:"):
        parser.error("Use HTTPS for Core connections (localhost HTTP allowed for testing)")
    rclpy.init()
    node = RosStatusNode(args.scan_topic, args.map_topic, args.map_frame, args.base_frame)
    stop = threading.Event()
    spin_thread = threading.Thread(target=ros_spin, args=(node, stop), daemon=True)
    spin_thread.start()
    try:
        asyncio.run(bridge_loop(args, node))
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        spin_thread.join(timeout=2)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
