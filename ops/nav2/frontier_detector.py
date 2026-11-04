#!/usr/bin/env python3
"""Read-only frontier detection and Nav2 path verification.

ComputePathToPose only: never call NavigateToPose, publish cmd_vel, or arm motors.
"""
from collections import deque
import math

import rclpy
from geometry_msgs.msg import Point, PoseStamped
from nav_msgs.msg import Path
from nav2_msgs.action import ComputePathToPose, NavigateToPose
from action_msgs.msg import GoalStatus
from sensor_msgs.msg import LaserScan
from rclpy.qos import qos_profile_sensor_data
from std_srvs.srv import Trigger, SetBool
from rclpy.action import ActionClient
from rclpy.time import Time
from tf2_ros import Buffer, TransformListener
import time
from nav_msgs.msg import OccupancyGrid
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from visualization_msgs.msg import Marker, MarkerArray


class FrontierDetector(Node):
    def __init__(self):
        super().__init__("jarvis_frontier_detector")
        self.declare_parameter("minimum_cluster_cells", 6)
        self.declare_parameter("maximum_clusters", 40)
        self.declare_parameter("update_period_seconds", 3.0)
        self.declare_parameter("free_threshold", 20)
        self._latest_map = None
        self._map_received_at = None
        self._scan_received_at = {"upper": None, "lower": None}
        self._mode = "idle"  # Never autonomously drive on boot or after restart.
        self._last_reason = "Not started"
        self._failure_count = 0
        self._completed_goals = 0
        self._rejected_points = []
        self._navigation_handle = None
        self._navigation_pending = False
        self._generation = 0
        self._planning = False
        self._candidates = []
        self._candidate_index = 0
        self._evaluated = []
        self._best = None
        self._batch_started = 0.0
        self._next_batch = 0.0
        self._active_goal = None
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)
        self._plan_client = ActionClient(self, ComputePathToPose, "/compute_path_to_pose")
        self._nav_client = ActionClient(self, NavigateToPose, "/navigate_to_pose")
        self._disarm_client = self.create_client(SetBool, "/jarvis_drive/set_armed")
        self.create_subscription(LaserScan, "/scan", lambda msg: self.on_scan("upper"), qos_profile_sensor_data)
        self.create_subscription(LaserScan, "/scan_lower", lambda msg: self.on_scan("lower"), qos_profile_sensor_data)
        self.create_service(Trigger, "/jarvis/exploration/start", self.start_exploration)
        self.create_service(Trigger, "/jarvis/exploration/stop", self.stop_exploration)
        self.create_service(Trigger, "/jarvis/exploration/status", self.exploration_status)
        self.create_timer(0.25, self.check_exploration_health)
        self.declare_parameter("planning_interval_seconds", 20.0)
        self.declare_parameter("staging_distance_m", 0.35)
        self.declare_parameter("maximum_candidates_to_plan", 5)
        self.declare_parameter("minimum_goal_distance_m", 0.30)
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(OccupancyGrid, "/map", self.on_map, qos)
        self._markers = self.create_publisher(MarkerArray, "/jarvis/exploration/frontiers", qos)
        self._selection = self.create_publisher(MarkerArray, "/jarvis/exploration/selection", qos)
        self._selected_path = self.create_publisher(Path, "/jarvis/exploration/selected_path", qos)
        self.create_timer(float(self.get_parameter("update_period_seconds").value),
                          self.publish_frontiers)
        self.get_logger().info("Frontier planning preview enabled (READ ONLY): /map + ComputePathToPose")

    def on_map(self, message):
        self._latest_map = message
        self._map_received_at = time.monotonic()

    def on_scan(self, which):
        self._scan_received_at[which] = time.monotonic()

    def healthy(self):
        now = time.monotonic()
        if self._map_received_at is None or now - self._map_received_at > 20.0:
            return False, "Map updates unavailable or older than 20 seconds"
        for name, seen in self._scan_received_at.items():
            if seen is None or now - seen > 2.0:
                return False, f"{name} LiDAR scan older than 2 seconds"
        if self.robot_pose("map") is None:
            return False, "Localization transform missing or older than 1 second"
        return True, "OK"

    def start_exploration(self, request, response):
        if self._mode == "exploring":
            response.success = False
            response.message = "Already exploring"
            return response
        if self._navigation_pending or self._navigation_handle is not None:
            response.success = False
            response.message = "Navigation still settling; retry shortly"
            return response
        healthy, reason = self.healthy()
        if not healthy or not self._nav_client.server_is_ready() or not self._plan_client.server_is_ready():
            response.success = False
            response.message = reason if not healthy else "Nav2 action servers not ready"
            return response
        self._generation += 1
        self._mode = "exploring"
        self._last_reason = "Exploration started; selecting frontier"
        self._failure_count = 0
        self._completed_goals = 0
        self._rejected_points.clear()
        self._next_batch = 0.0
        response.success = True
        response.message = "Exploration enabled; motors must be armed separately"
        self.get_logger().warning("EXPLORATION STARTED by explicit ROS service command")
        return response

    def stop_exploration(self, request, response):
        self.halt_exploration("Stopped by operator", disarm=True)
        response.success = True
        response.message = "Exploration stopped; cancel and disarm requested"
        return response

    def exploration_status(self, request, response):
        response.success = True
        response.message = (f"mode={self._mode}, goals_completed={self._completed_goals}, "
                            f"consecutive_failures={self._failure_count}, "
                            f"reason={self._last_reason}")
        return response

    def request_disarm(self):
        if not self._disarm_client.service_is_ready():
            self.get_logger().error("Drive disarm service unavailable; operator must cut motor power")
            return
        req = SetBool.Request()
        req.data = False
        future = self._disarm_client.call_async(req)
        def reported(result_future):
            try:
                result = result_future.result()
                if not result.success:
                    self.get_logger().error(f"Drive disarm refused: {result.message}")
            except Exception as exc:
                self.get_logger().error(f"Drive disarm failed: {type(exc).__name__}")
        future.add_done_callback(reported)

    def halt_exploration(self, reason, disarm=True):
        self._mode = "idle"
        self._last_reason = reason
        self._generation += 1
        self._next_batch = time.monotonic() + 2.0
        self.get_logger().warning(f"EXPLORATION HALTED: {reason}")
        if self._navigation_handle is not None:
            try:
                self._navigation_handle.cancel_goal_async()
            except Exception as exc:
                self.get_logger().error(f"Nav2 cancellation failed: {type(exc).__name__}")
        if disarm:
            self.request_disarm()

    def check_exploration_health(self):
        if self._mode != "exploring":
            return
        healthy, reason = self.healthy()
        if not healthy:
            self.halt_exploration(reason)

    def is_rejected(self, position):
        return any(math.hypot(position.x - old_x, position.y - old_y) < 0.40
                   for old_x, old_y in self._rejected_points)

    def goal_failed(self, reason, position):
        if self._mode != "exploring":
            return
        self._failure_count += 1
        self._rejected_points.append((position.x, position.y))
        self._last_reason = reason
        self.get_logger().warning(
            f"Exploration goal failed ({self._failure_count}/3): {reason}")
        if self._failure_count >= 3:
            self.halt_exploration("Three consecutive failed Nav2 goals")
        else:
            self._next_batch = 0.0

    def send_navigation(self):
        if self._mode != "exploring" or self._best is None:
            return
        healthy, reason = self.healthy()
        if not healthy:
            self.halt_exploration(reason)
            return
        _, length, path, stage, frontier, count = self._best
        if self.is_rejected(stage):
            return
        angle = math.atan2(frontier.y - stage.y, frontier.x - stage.x)
        from geometry_msgs.msg import Quaternion
        heading = Quaternion(z=math.sin(angle / 2), w=math.cos(angle / 2))
        goal = NavigateToPose.Goal()
        goal.pose = self.make_pose(self._frame, stage, heading, self.get_clock())
        self._navigation_pending = True
        generation = self._generation
        self._last_reason = f"Navigating to ({stage.x:.2f}, {stage.y:.2f})"
        self.get_logger().warning(f"Sending Nav2 exploration goal: {self._last_reason}")
        try:
            future = self._nav_client.send_goal_async(goal)
            future.add_done_callback(lambda f: self.on_navigation_accepted(f, generation, stage))
        except Exception as exc:
            self._navigation_pending = False
            self.goal_failed(f"Nav2 goal send error: {type(exc).__name__}", stage)

    def on_navigation_accepted(self, future, generation, position):
        self._navigation_pending = False
        try:
            handle = future.result()
            self._navigation_handle = handle if handle.accepted else None
            if generation != self._generation or self._mode != "exploring":
                if handle.accepted:
                    handle.cancel_goal_async()
                return
            if not handle.accepted:
                self.goal_failed("Nav2 rejected navigation goal", position)
                return
            handle.get_result_async().add_done_callback(
                lambda f: self.on_navigation_result(f, generation, position))
        except Exception as exc:
            self.goal_failed(f"Nav2 goal acceptance error: {type(exc).__name__}", position)

    def on_navigation_result(self, future, generation, position):
        self._navigation_handle = None
        if generation != self._generation or self._mode != "exploring":
            return
        try:
            status = future.result().status
            if status == GoalStatus.STATUS_SUCCEEDED:
                self._completed_goals += 1
                self._failure_count = 0
                self._last_reason = f"Reached frontier {self._completed_goals}"
                self.get_logger().info(self._last_reason)
                # Wait for the map to incorporate newly visible space.
                self._next_batch = time.monotonic() + 3.0
                return
            self.goal_failed(f"Nav2 returned status {status}", position)
        except Exception as exc:
            self.goal_failed(f"Nav2 result error: {type(exc).__name__}", position)


    @staticmethod
    def find_clusters(message, free_threshold=20, min_size=6, max_clusters=40):
        width, height = message.info.width, message.info.height
        cells = message.data
        if width < 3 or height < 3 or len(cells) != width * height:
            return []
        # Only observed free cells directly bordering unknown space qualify.
        # Use 4-connectivity for adjacency so diagonal wall corners do not
        # masquerade as a passable opening.
        frontier = bytearray(width * height)
        for y in range(1, height - 1):
            start = y * width
            for x in range(1, width - 1):
                i = start + x
                if 0 <= cells[i] <= free_threshold and (
                    cells[i - 1] == -1 or cells[i + 1] == -1
                    or cells[i - width] == -1 or cells[i + width] == -1
                ):
                    frontier[i] = 1
        clusters = []
        for seed in range(len(frontier)):
            if not frontier[seed]:
                continue
            frontier[seed] = 0
            pending = deque([seed])
            cluster = []
            while pending:
                index = pending.popleft()
                cluster.append(index)
                x, y = index % width, index // width
                for neighbor in (
                    index - 1 if x > 0 else -1,
                    index + 1 if x < width - 1 else -1,
                    index - width if y > 0 else -1,
                    index + width if y < height - 1 else -1,
                ):
                    if neighbor >= 0 and frontier[neighbor]:
                        frontier[neighbor] = 0
                        pending.append(neighbor)
            if len(cluster) >= min_size:
                clusters.append(cluster)
        clusters.sort(key=len, reverse=True)
        return clusters[:max_clusters]

    @staticmethod
    def world_point(message, index):
        info = message.info
        x = index % info.width
        y = index // info.width
        local_x = (x + 0.5) * info.resolution
        local_y = (y + 0.5) * info.resolution
        origin = info.origin
        q = origin.orientation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y),
                         1 - 2 * (q.y * q.y + q.z * q.z))
        c, s = math.cos(yaw), math.sin(yaw)
        return Point(x=origin.position.x + c * local_x - s * local_y,
                     y=origin.position.y + s * local_x + c * local_y, z=0.035)

    def publish_frontiers(self):
        message = self._latest_map
        if message is None:
            return
        self._latest_map = None  # Work only on new maps; no repeated full-grid scans.
        clusters = self.find_clusters(
            message, int(self.get_parameter("free_threshold").value),
            int(self.get_parameter("minimum_cluster_cells").value),
            int(self.get_parameter("maximum_clusters").value))
        frame = message.header.frame_id or "map"
        now = self.get_clock().now().to_msg()
        clear = Marker()
        clear.header.frame_id = frame
        clear.header.stamp = now
        clear.action = Marker.DELETEALL
        markers = MarkerArray(markers=[clear])
        for number, cluster in enumerate(clusters):
            points = Marker()
            points.header.frame_id = frame
            points.header.stamp = now
            points.ns = "frontier_cells"
            points.id = number
            points.type = Marker.POINTS
            points.action = Marker.ADD
            points.pose.orientation.w = 1.0
            points.scale.x = max(0.025, message.info.resolution * 0.7)
            points.scale.y = points.scale.x
            points.color.r, points.color.g, points.color.b, points.color.a = (0.1, 0.95, 0.8, 0.95)
            points.points = [self.world_point(message, i) for i in cluster]
            markers.markers.append(points)

            # Display a representative on an actual free frontier cell,
            # not the arithmetic centroid (which may lie inside a wall).
            mean_x = sum(i % message.info.width for i in cluster) / len(cluster)
            mean_y = sum(i // message.info.width for i in cluster) / len(cluster)
            representative = min(cluster,
                key=lambda i: (i % message.info.width - mean_x)**2
                            + (i // message.info.width - mean_y)**2)
            target = Marker()
            target.header.frame_id = frame
            target.header.stamp = now
            target.ns = "frontier_representatives"
            target.id = number
            target.type = Marker.SPHERE
            target.action = Marker.ADD
            target.pose.position = self.world_point(message, representative)
            target.pose.orientation.w = 1.0
            target.scale.x = target.scale.y = target.scale.z = 0.10
            target.color.r, target.color.g, target.color.b, target.color.a = (1.0, 0.65, 0.05, 1.0)
            markers.markers.append(target)
        self._markers.publish(markers)
        self.start_planning_preview(message, clusters)
        self.get_logger().info(
            f"Frontier clusters={len(clusters)} "
            f"(largest cells={len(clusters[0]) if clusters else 0}); visualization only")


    @staticmethod
    def point_is_clear(message, x, y, radius):
        """Require a known-free circular neighborhood, not just one free cell."""
        info = message.info
        radius_cells = int(math.ceil(radius / info.resolution))
        for dy in range(-radius_cells, radius_cells + 1):
            for dx in range(-radius_cells, radius_cells + 1):
                if dx * dx + dy * dy > (radius / info.resolution) ** 2:
                    continue
                xx, yy = x + dx, y + dy
                if xx < 0 or xx >= info.width or yy < 0 or yy >= info.height:
                    return False
                if message.data[yy * info.width + xx] < 0 or message.data[yy * info.width + xx] > 20:
                    return False
        return True

    @classmethod
    def staging_point(cls, message, cluster, distance):
        """Pick a known-free interior cell with footprint room behind a frontier."""
        info = message.info
        width, height = info.width, info.height
        frontier_center_x = sum(i % width for i in cluster) / len(cluster)
        frontier_center_y = sum(i // width for i in cluster) / len(cluster)
        radius = max(1, int(math.ceil((distance + 0.2) / info.resolution)))
        options = []
        for index in sorted(cluster, key=lambda i:
                            (i % width - frontier_center_x)**2 +
                            (i // width - frontier_center_y)**2)[:min(8, len(cluster))]:
            fx, fy = index % width, index // width
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    distance_m = math.hypot(dx, dy) * info.resolution
                    if distance_m < distance * 0.8 or distance_m > distance + 0.15:
                        continue
                    xx, yy = fx + dx, fy + dy
                    if not (0 <= xx < width and 0 <= yy < height):
                        continue
                    if cls.point_is_clear(message, xx, yy, 0.23):
                        options.append((abs(distance_m - distance)
                                        + 0.01 * math.hypot(xx-frontier_center_x, yy-frontier_center_y),
                                        yy * width + xx, index))
            if options:
                break
        if not options:
            return None
        _, staging_index, frontier_index = min(options)
        return cls.world_point(message, staging_index), cls.world_point(message, frontier_index)

    def robot_pose(self, frame):
        try:
            tf = self._tf_buffer.lookup_transform(frame, "base_link", Time())
            stamp = tf.header.stamp
            if stamp.sec == 0 and stamp.nanosec == 0:
                return None
            stamp_seconds = stamp.sec + stamp.nanosec * 1e-9
            if abs(self.get_clock().now().nanoseconds * 1e-9 - stamp_seconds) > 1.0:
                return None
            return tf.transform.translation, tf.transform.rotation
        except Exception:
            return None

    @staticmethod
    def make_pose(frame, position, quaternion, clock):
        pose = PoseStamped()
        pose.header.frame_id = frame
        pose.header.stamp = clock.now().to_msg()
        pose.pose.position.x = position.x
        pose.pose.position.y = position.y
        pose.pose.orientation = quaternion
        return pose

    def start_planning_preview(self, message, clusters):
        now = time.monotonic()
        if self._planning or self._navigation_pending or self._navigation_handle is not None or now < self._next_batch:
            return
        self._next_batch = now + float(self.get_parameter("planning_interval_seconds").value)
        # Empty frontiers invalidate any previously rendered selection.
        self.clear_selection(message.header.frame_id or "map")
        if not clusters:
            return
        frame = message.header.frame_id or "map"
        robot = self.robot_pose(frame)
        if robot is None or not self._plan_client.server_is_ready():
            self.get_logger().info("Preview waiting for fresh robot TF and ACTIVE Nav2 planner")
            return
        position, orientation = robot
        candidates = []
        for cluster in clusters[:20]:
            stage = self.staging_point(
                message, cluster, float(self.get_parameter("staging_distance_m").value))
            if stage is None:
                continue
            goal_pos, frontier_pos = stage
            direct = math.hypot(goal_pos.x - position.x, goal_pos.y - position.y)
            if direct < float(self.get_parameter("minimum_goal_distance_m").value) or self.is_rejected(goal_pos):
                continue
            # Prefer large frontiers while keeping travel reasonable; the
            # actual ranking only uses successfully computed Nav2 path lengths.
            priority = direct - 0.012 * min(len(cluster), 100)
            candidates.append((priority, len(cluster), goal_pos, frontier_pos))
        candidates.sort(key=lambda item: item[0])
        limit = int(self.get_parameter("maximum_candidates_to_plan").value)
        self._candidates = candidates[:max(0, limit)]
        if not self._candidates:
            self.get_logger().info("No frontier staging cells with clear known-free footprint")
            if self._mode == "exploring":
                self.halt_exploration("No eligible frontiers remain")
            return
        self._start_pose = self.make_pose(frame, position, orientation, self.get_clock())
        self._frame = frame
        self._candidate_index = 0
        self._best = None
        self._evaluated = []
        self._planning = True
        self._batch_started = now
        self.get_logger().info(f"Checking {len(self._candidates)} frontier paths with Nav2 (no driving)")
        self.plan_next()

    def plan_next(self):
        if not self._planning:
            return
        if self._candidate_index >= len(self._candidates):
            self.finish_batch()
            return
        # Never let an unresponsive action leave a permanent pending preview.
        if time.monotonic() - self._batch_started > 25.0:
            self.get_logger().warning("Frontier preview batch timed out; will retry later")
            self.finish_batch()
            return
        _, count, position, frontier = self._candidates[self._candidate_index]
        angle = math.atan2(frontier.y - position.y, frontier.x - position.x)
        from geometry_msgs.msg import Quaternion
        heading = Quaternion(z=math.sin(angle / 2), w=math.cos(angle / 2))
        goal = ComputePathToPose.Goal()
        goal.start = self._start_pose
        goal.goal = self.make_pose(self._frame, position, heading, self.get_clock())
        goal.planner_id = "GridBased"
        goal.use_start = True
        try:
            future = self._plan_client.send_goal_async(goal)
            future.add_done_callback(self.on_plan_accepted)
        except Exception as exc:
            self.get_logger().warning(f"Planner request failed: {type(exc).__name__}")
            self._candidate_index += 1
            self.plan_next()

    def on_plan_accepted(self, future):
        try:
            handle = future.result()
            if not handle.accepted:
                self._candidate_index += 1
                self.plan_next()
                return
            self._active_goal = handle
            handle.get_result_async().add_done_callback(self.on_plan_result)
        except Exception as exc:
            self.get_logger().warning(f"Planner goal acceptance failed: {type(exc).__name__}")
            self._candidate_index += 1
            self.plan_next()

    def on_plan_result(self, future):
        try:
            response = future.result()
            result = response.result
            path = result.path
            if response.status == 4 and result.error_code == 0 and len(path.poses) >= 2:
                length = sum(math.hypot(
                    b.pose.position.x - a.pose.position.x,
                    b.pose.position.y - a.pose.position.y)
                    for a, b in zip(path.poses, path.poses[1:]))
                _, cluster_size, stage, frontier = self._candidates[self._candidate_index]
                # Small information-gain bonus, but path length remains dominant.
                score = length - 0.012 * min(cluster_size, 100)
                self._evaluated.append((score, length))
                if self._best is None or score < self._best[0]:
                    self._best = (score, length, path, stage, frontier, cluster_size)
        except Exception as exc:
            self.get_logger().warning(f"Planner result unavailable: {type(exc).__name__}")
        finally:
            self._active_goal = None
            self._candidate_index += 1
            self.plan_next()

    def clear_selection(self, frame):
        clear = Marker()
        clear.header.frame_id = frame
        clear.header.stamp = self.get_clock().now().to_msg()
        clear.action = Marker.DELETEALL
        self._selection.publish(MarkerArray(markers=[clear]))
        blank = Path()
        blank.header.frame_id = frame
        blank.header.stamp = clear.header.stamp
        self._selected_path.publish(blank)

    def finish_batch(self):
        self._planning = False
        if self._best is None:
            self.get_logger().info("Preview: no valid Nav2 path among tested frontiers")
            if self._mode == "exploring":
                self.halt_exploration("No reachable frontier among checked candidates")
            return
        _, length, path, stage, frontier, count = self._best
        marker = Marker()
        marker.header.frame_id = self._frame
        marker.header.stamp = self.get_clock().now().to_msg()
        marker.ns = "selected_staging_point"
        marker.id = 0
        marker.type = Marker.SPHERE
        marker.action = Marker.ADD
        marker.pose.position = stage
        marker.pose.orientation.w = 1.0
        marker.scale.x = marker.scale.y = marker.scale.z = 0.16
        marker.color.r, marker.color.g, marker.color.b, marker.color.a = 0.15, 0.35, 1.0, 1.0
        self._selection.publish(MarkerArray(markers=[marker]))
        path.header.frame_id = self._frame
        self._selected_path.publish(path)
        self.get_logger().info(
            f"Preview best frontier: cluster={count} cells, path={length:.2f}m, "
            f"goal=({stage.x:.2f},{stage.y:.2f}); "
            f"exploration_mode={self._mode}")
        if self._mode == "exploring":
            self.send_navigation()


def main():
    rclpy.init()
    node = FrontierDetector()
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
