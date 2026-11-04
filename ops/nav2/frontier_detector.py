#!/usr/bin/env python3
"""Read-only frontier discovery for Jarvis's live slam_toolbox occupancy map.

No Nav2 actions, velocity commands, or motor connections. Candidate markers
are *observations*, not validated or reachable navigation destinations.
"""
from collections import deque
import math

import rclpy
from geometry_msgs.msg import Point
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
        self._latest_stamp = None
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(OccupancyGrid, "/map", self.on_map, qos)
        self._markers = self.create_publisher(MarkerArray, "/jarvis/exploration/frontiers", qos)
        self.create_timer(float(self.get_parameter("update_period_seconds").value),
                          self.publish_frontiers)
        self.get_logger().info("Frontier detection active (READ ONLY): /map -> /jarvis/exploration/frontiers")

    def on_map(self, message):
        self._latest_map = message

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
        self.get_logger().info(
            f"Frontier clusters={len(clusters)} "
            f"(largest cells={len(clusters[0]) if clusters else 0}); visualization only")


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
