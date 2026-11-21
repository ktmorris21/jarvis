"""Launch Jarvis Nav2, including bounded Ackermann-compatible recovery.

Existing jarvis-mapping supplies SLAM, RF2O and LiDAR; do not duplicate it.
Nav2 publishes directly to /cmd_vel, and the drive is disarmed on boot.
"""
from pathlib import Path

from launch import LaunchDescription
from launch.actions import ExecuteProcess
from launch_ros.actions import Node

HERE = Path(__file__).resolve().parent
PARAMS = str(HERE / "jarvis_nav2.yaml")

NODES = ("controller_server", "planner_server", "behavior_server", "bt_navigator")


def generate_launch_description():
    nodes = [
        ExecuteProcess(
            cmd=["/usr/bin/python3", "-u", str(HERE / "frontier_detector.py")],
            output="screen",
        ),
        Node(
            package="nav2_controller",
            executable="controller_server",
            name="controller_server",
            output="screen",
            parameters=[PARAMS],
        ),
        Node(
            package="nav2_planner",
            executable="planner_server",
            name="planner_server",
            output="screen",
            parameters=[PARAMS],
        ),
        Node(
            package="nav2_behaviors",
            executable="behavior_server",
            name="behavior_server",
            output="screen",
            parameters=[PARAMS],
        ),
        Node(
            package="nav2_bt_navigator",
            executable="bt_navigator",
            name="bt_navigator",
            output="screen",
            parameters=[PARAMS],
        ),
        Node(
            package="nav2_lifecycle_manager",
            executable="lifecycle_manager",
            name="lifecycle_manager_navigation",
            output="screen",
            parameters=[{
                "autostart": True,
                "node_names": list(NODES),
            }],
        ),
    ]
    return LaunchDescription(nodes)
