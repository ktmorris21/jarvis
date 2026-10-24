#!/usr/bin/env bash
set -euo pipefail
source /opt/ros/jazzy/setup.bash
source "$HOME/ros2_ws/install/setup.bash"
cd "$HOME/jarvis"
# URL and token come from the root-owned systemd EnvironmentFile.
# They are not placed on the Python process command line.
exec /usr/bin/python3 -m body_services.picar.ros_bridge \
  --interface-id picar-ros --base-frame base_link
