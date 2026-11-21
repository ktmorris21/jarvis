"""Static regression tests for Jarvis's bounded Nav2 recovery wiring.

No hardware motion or ROS runtime is exercised here.
"""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
NAV = ROOT / "ops" / "nav2"


class TestBoundedNavRecovery(unittest.TestCase):
    def test_recovery_tree_is_bounded_and_keeps_original_goal(self):
        root = ET.parse(NAV / "point_to_point.xml").getroot()
        recovery = root.find(".//RecoveryNode")
        self.assertIsNotNone(recovery)
        self.assertEqual(recovery.attrib["number_of_retries"], "2")
        backup = recovery.find("BackUp")
        self.assertIsNotNone(backup)
        self.assertEqual(backup.attrib["server_name"], "backup")
        self.assertGreater(float(backup.attrib["backup_dist"]), 0)
        self.assertLessEqual(float(backup.attrib["backup_dist"]), 0.10)
        self.assertLessEqual(float(backup.attrib["time_allowance"]), 5.0)
        self.assertEqual(recovery.find(".//ComputePathToPose").attrib["goal"], "{goal}")
        self.assertEqual(
            recovery.find(".//FollowPath").attrib["goal_checker_id"],
            "goal_checker",
        )
        self.assertFalse(list(root.iter("Spin")))
        self.assertFalse(list(root.iter("DriveOnHeading")))

    def test_behavior_server_is_in_launch_and_lifecycle(self):
        launch = (NAV / "navigation.launch.py").read_text()
        self.assertIn('"behavior_server"', launch)
        self.assertIn('package="nav2_behaviors"', launch)
        self.assertIn('executable="behavior_server"', launch)
        self.assertIn('"node_names": list(NODES)', launch)

    def test_backup_checks_costmap_and_only_registers_backup(self):
        yaml = (NAV / "jarvis_nav2.yaml").read_text()
        behavior = yaml.split("\nbehavior_server:", 1)[1].split("\nplanner_server:", 1)[0]
        self.assertIn('behavior_plugins: ["backup"]', behavior)
        self.assertIn('plugin: "nav2_behaviors::BackUp"', behavior)
        self.assertIn("local_costmap_topic: local_costmap/costmap_raw", behavior)
        self.assertIn("local_footprint_topic: local_costmap/published_footprint", behavior)


if __name__ == "__main__":
    unittest.main()
