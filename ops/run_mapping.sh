#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/jazzy/setup.bash
source "$HOME/ros2_ws/install/setup.bash"
# Preserve the currently working mapping launch and its default arguments.
# We will explicitly configure verified resume arguments later.
exec ros2 launch jarvis_bringup mapping.launch.py
