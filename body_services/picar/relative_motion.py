"""Bounded, footprint-checked relative motion via Nav2 FollowPath.

No motor arming or direct /cmd_vel publishing. Runs inside the ROS bridge.
The action follows a fixed straight path; it is never allowed to plan a detour.
"""
import asyncio
import json
import math
import time
from uuid import uuid4

from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import OccupancyGrid, Path
from nav2_msgs.action import FollowPath
from action_msgs.msg import GoalStatus
from rclpy.action import ActionClient
from rclpy.qos import qos_profile_sensor_data
from std_srvs.srv import Trigger
from tf2_ros import TransformException
from rclpy.time import Time

MAX_DISTANCE_M = 0.9144  # Three feet per request; never accept unbounded motion.
MIN_DISTANCE_M = 0.08
BODY_FRONT_M = 0.2032
BODY_REAR_M = -0.09525
BODY_HALF_WIDTH_M = 0.073025
CLEARANCE_M = 0.035


def validate_move(data):
    if not isinstance(data, dict) or set(data) != {"direction", "distance_m"}:
        raise ValueError("Expected direction and distance_m only")
    direction = data["direction"]
    distance = data["distance_m"]
    if direction not in ("forward", "backward") or isinstance(distance, bool) or not isinstance(distance, (int, float)):
        raise ValueError("Use forward/backward and a numeric distance in meters")
    if not math.isfinite(distance) or not MIN_DISTANCE_M <= distance <= MAX_DISTANCE_M:
        raise ValueError("Distance must be 0.08 to 0.9144 meters")
    return direction, float(distance)


def yaw_of(q):
    return math.atan2(2 * (q.w * q.z + q.x * q.y),
                      1 - 2 * (q.y * q.y + q.z * q.z))


def footprint_corridor_clear(grid, x, y, yaw, signed_distance):
    """Require known-free cells under every part of the swept rectangular body."""
    if grid is None or grid.info.resolution <= 0 or not grid.data:
        return False, "Costmap unavailable"
    res = float(grid.info.resolution)
    width, height = grid.info.width, grid.info.height
    origin = grid.info.origin
    origin_yaw = yaw_of(origin.orientation)
    oc, os = math.cos(origin_yaw), math.sin(origin_yaw)
    c, s = math.cos(yaw), math.sin(yaw)
    step = min(0.025, res / 2)
    n = max(1, math.ceil(abs(signed_distance) / step))
    nx = max(1, math.ceil((BODY_FRONT_M - BODY_REAR_M + 2*CLEARANCE_M) / step))
    ny = max(1, math.ceil((2*BODY_HALF_WIDTH_M + 2*CLEARANCE_M) / step))
    for i in range(n + 1):
        offset = signed_distance * i / n
        for j in range(nx + 1):
            dx = offset + BODY_REAR_M - CLEARANCE_M + (BODY_FRONT_M - BODY_REAR_M + 2*CLEARANCE_M) * j/nx
            for k in range(ny + 1):
                dy = -BODY_HALF_WIDTH_M - CLEARANCE_M + (2*BODY_HALF_WIDTH_M + 2*CLEARANCE_M) * k/ny
                wx, wy = x + c*dx - s*dy, y + s*dx + c*dy
                rx, ry = wx-origin.position.x, wy-origin.position.y
                gx = math.floor((oc*rx + os*ry)/res)
                gy = math.floor((-os*rx + oc*ry)/res)
                if not (0 <= gx < width and 0 <= gy < height):
                    return False, "Requested corridor extends outside the observed costmap"
                cell = grid.data[gy*width + gx]
                if cell < 0:
                    return False, "Requested corridor contains unknown space"
                if cell >= 65:
                    return False, "Obstacle or inflated collision zone in requested corridor"
    return True, "clear"


async def ros_future(future, timeout=3.0):
    end = time.monotonic() + timeout
    while not future.done() and time.monotonic() < end:
        await asyncio.sleep(0.025)
    if not future.done():
        future.cancel()
        raise TimeoutError("ROS response timed out")
    return future.result()


class RelativeMotion:
    def __init__(self, node):
        self.node = node
        self.costmap = None
        self.costmap_at = None
        self.active = None
        self.pending = False
        self.arm_client = node.create_client(Trigger, "/jarvis_drive/status")
        self.explore_client = node.exploration_services["exploration_status"]
        self.follow_client = ActionClient(node, FollowPath, "/follow_path")
        node.create_subscription(OccupancyGrid, "/global_costmap/costmap", self.on_costmap, 1)
        node.create_timer(0.2, self.watchdog)

    def on_costmap(self, msg):
        self.costmap, self.costmap_at = msg, time.monotonic()

    def pose(self):
        tf = self.node.tf_buffer.lookup_transform("map", self.node.base_frame, Time())
        stamp = tf.header.stamp.sec + tf.header.stamp.nanosec * 1e-9
        age = self.node.get_clock().now().nanoseconds * 1e-9 - stamp
        if not stamp or not -0.5 <= age <= 2.0:
            raise ValueError("Localization is stale")
        p, q = tf.transform.translation, tf.transform.rotation
        if not all(math.isfinite(v) for v in (p.x, p.y, q.x, q.y, q.z, q.w)):
            raise ValueError("Localization contains invalid coordinates")
        return p.x, p.y, yaw_of(q)

    def health(self):
        now = time.monotonic()
        for name, t in (("upper LiDAR", self.node.last_scan_at),
                        ("lower LiDAR", self.node.last_lower_scan_at),
                        ("RF2O odometry", self.node._odom_at)):
            if t is None or now-t > 1.5:
                return False, name + " is unavailable or stale"
        if self.costmap_at is None or now-self.costmap_at > 2.5:
            return False, "Nav2 global costmap unavailable or stale"
        try:
            self.pose()
        except Exception:
            return False, "Fresh localization unavailable"
        return True, "OK"

    @staticmethod
    def path(node, x, y, heading, signed_distance):
        result = Path()
        result.header.frame_id = "map"
        result.header.stamp = node.get_clock().now().to_msg()
        steps = max(2, math.ceil(abs(signed_distance)/0.05))
        for i in range(steps+1):
            pose = PoseStamped()
            pose.header = result.header
            pose.pose.position.x = x + math.cos(heading)*signed_distance*i/steps
            pose.pose.position.y = y + math.sin(heading)*signed_distance*i/steps
            pose.pose.orientation.z = math.sin(heading/2)
            pose.pose.orientation.w = math.cos(heading/2)
            result.poses.append(pose)
        return result

    async def move(self, data):
        try:
            direction, distance = validate_move(data)
        except ValueError as exc:
            return {"success": False, "message": str(exc)}
        if self.pending or self.active is not None:
            return {"success": False, "message": "Relative movement already in progress"}
        self.pending = True
        try:
            healthy, reason = self.health()
            if not healthy:
                return {"success": False, "message": reason}
            if not self.follow_client.server_is_ready():
                return {"success": False, "message": "Nav2 FollowPath controller is unavailable"}
            if any(status in (1, 2, 3) for status in self.node._nav_goal_status.values()):
                return {"success": False, "message": "Another Nav2 navigation goal is active"}
            if not self.arm_client.service_is_ready() or not self.explore_client.service_is_ready():
                return {"success": False, "message": "Drive or exploration status unavailable"}
            arm = await ros_future(self.arm_client.call_async(Trigger.Request()))
            if not arm.success:
                return {"success": False, "message": "Drive status unavailable"}
            drive = json.loads(arm.message)
            if not drive.get("armed") or not drive.get("hardware_enabled"):
                return {"success": False, "message": "Motors are disarmed or hardware drive is disabled"}
            exploration = await ros_future(self.explore_client.call_async(Trigger.Request()))
            if not exploration.success or "mode=idle" not in exploration.message:
                return {"success": False, "message": "Exploration is active or its status is unavailable"}
            x, y, heading = self.pose()
            signed = distance if direction == "forward" else -distance
            clear, reason = footprint_corridor_clear(self.costmap, x, y, heading, signed)
            if not clear:
                return {"success": False, "message": reason}
            # Require the health check again after remote service calls.
            healthy, reason = self.health()
            if not healthy:
                return {"success": False, "message": reason}
            goal = FollowPath.Goal()
            goal.path = self.path(self.node, x, y, heading, signed)
            goal.controller_id = "FollowPath"
            goal.goal_checker_id = "relative_goal_checker"
            handle = await ros_future(self.follow_client.send_goal_async(goal), timeout=3.0)
            if not handle.accepted:
                return {"success": False, "message": "Nav2 rejected the relative path"}
            motion_id = uuid4().hex[:12]
            self.active = {"handle": handle, "id": motion_id, "start": time.monotonic(),
                           "x": x, "y": y, "yaw": heading, "distance": signed,
                           "last_progress": time.monotonic(), "best_progress": 0.0}
            handle.get_result_async().add_done_callback(self.on_result)
            self.node.get_logger().warning("RELATIVE_MOTION_ACCEPTED " + json.dumps(
                {"motion_id": motion_id, "direction": direction, "distance_m": distance}))
            return {"success": True, "accepted": True, "completed": False,
                    "motion_id": motion_id, "direction": direction, "distance_m": distance,
                    "message": "Nav2 accepted a straight relative path; completion not yet verified"}
        except (ValueError, TimeoutError, json.JSONDecodeError) as exc:
            return {"success": False, "message": str(exc)}
        except Exception as exc:
            self.node.get_logger().error("Relative motion request failed: " + type(exc).__name__)
            return {"success": False, "message": "Relative motion controller unavailable"}
        finally:
            self.pending = False

    def on_result(self, future):
        state = self.active
        if state is None:
            return
        try:
            result = future.result()
            succeeded = result.status == GoalStatus.STATUS_SUCCEEDED
            detail = "succeeded" if succeeded else "failed_or_canceled"
        except Exception:
            detail = "result_unavailable"
        self.node.get_logger().warning("RELATIVE_MOTION_FINISHED " + json.dumps(
            {"motion_id": state["id"], "result": detail}))
        self.active = None

    def watchdog(self):
        state = self.active
        if state is None or state.get("canceling"):
            return
        healthy, reason = self.health()
        if healthy:
            try:
                x, y, heading = self.pose()
                dx, dy = x-state["x"], y-state["y"]
                progress = (dx*math.cos(state["yaw"]) + dy*math.sin(state["yaw"]))
                lateral = abs(-dx*math.sin(state["yaw"]) + dy*math.cos(state["yaw"]))
                signed_progress = progress if state["distance"] > 0 else -progress
                if lateral > 0.11 or signed_progress > abs(state["distance"])+0.12:
                    healthy, reason = False, "Deviation from straight path"
                elif signed_progress > state["best_progress"]+0.025:
                    state["best_progress"] = signed_progress
                    state["last_progress"] = time.monotonic()
                elif time.monotonic()-state["last_progress"] > 9.0:
                    healthy, reason = False, "No measured progress"
                if healthy:
                    remaining = state["distance"]-progress
                    clear, reason = footprint_corridor_clear(self.costmap, x, y, heading, remaining)
                    healthy = clear
            except Exception:
                healthy, reason = False, "Localization unavailable during motion"
        if time.monotonic()-state["start"] > max(15.0, abs(state["distance"])/0.05+12):
            healthy, reason = False, "Movement time limit exceeded"
        if not healthy:
            state["canceling"] = True
            self.node.get_logger().error("RELATIVE_MOTION_ABORT " + json.dumps(
                {"motion_id": state["id"], "reason": reason}))
            # Internal safety cancellation; no new user-facing stop command.
            try:
                state["handle"].cancel_goal_async()
            except Exception as exc:
                self.node.get_logger().error("RELATIVE_MOTION_CANCEL_FAILED " + type(exc).__name__)
