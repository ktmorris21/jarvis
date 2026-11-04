"""Start only Jarvis's needed Nav2 nodes, publishing DIRECTLY to /cmd_vel.

Mapping, slam_toolbox, RF2O, and both LiDAR drivers are provided by the
existing jarvis-mapping service; this launch must not duplicate them.
No separate velocity smoother or collision monitor process yet.
"""
from pathlib import Path

from launch import LaunchDescription
from launch_ros.actions import Node

HERE = Path(__file__).resolve().parent
PARAMS = str(HERE / "jarvis_nav2.yaml")

NODES = ("controller_server", "planner_server", "bt_navigator")


def generate_launch_description():
    nodes = [
        Node(
            package="nav2_controller",
            executable="controller_server",
            name="controller_server",
            output="screen",
            parameters=[PARAMS],
            # IMPORTANT: no cmd_vel remap. Publishes directly to /cmd_vel.
        ),
        Node(
            package="nav2_planner",
            executable="planner_server",
            name="planner_server",
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
