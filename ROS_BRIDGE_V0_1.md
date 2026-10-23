# ROS Status Bridge v0.1

Read-only connection from ROS 2 Jazzy on the Pi to the existing Railway Jarvis Core. It **does not** initialize the PiCar hardware, command motors, or send scans/maps to the cloud.

## Requirements
Run inside the Pi's ROS 2 Jazzy Python environment with `rclpy`, `sensor_msgs`, `nav_msgs`, `geometry_msgs`, and `tf2_ros` available, plus the repository's `websockets` Python dependency.

## Start
1. On the Pi, pull the feature branch and launch your existing LiDAR/SLAM stack.
2. In a second terminal:

```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
cd ~/jarvis
python3 -m body_services.picar.ros_bridge \
  --url "https://YOUR-RAILWAY-SERVICE" \
  --token "YOUR_JARVIS_INTERFACE_TOKEN" \
  --interface-id picar-ros \
  --base-frame base_link
```

Adjust checkout path and frame name to your actual Pi configuration. The shared token can be read in your secure shell environment instead of placing it directly in shell history.

## Test

Check `GET /state` for an online interface named `picar-ros` advertising only `get_robot_status`.

Then, from a separate terminal:
```bash
curl -sS -X POST 'https://YOUR-RAILWAY-SERVICE/debug/command' \
  -H "X-Jarvis-Token: YOUR_JARVIS_INTERFACE_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"target":"picar-ros","ability":"get_robot_status"}'
```

The command endpoint responds with `sent`; completion arrives asynchronously as a `COMMAND_RESULT` event. Find the matching `command_id` in `GET /actions`, and inspect `GET /state` for `robot_status:picar-ros` in `world_state`.

## Semantics
- `lidar.active`: a scan callback occurred within the preceding two seconds.
- `mapping.available`: a map message was received since bridge startup.
- `mapping.recent_update`: a map callback was observed within 60 seconds. An unchanged static map can still be valid; this is **not** proof of SLAM health.
- `pose.available`: a `map -> base_link` transform was obtainable. **Note:** pose freshness is not yet validated, so a cached transform may be stale. Treat the timestamp in `transform_stamp` as diagnostic, not a verified live pose.
- `received_at`: time Core stored the most recent successful response. An old record is stale even if its `lidar.active` is true.

## Safe failure exercise
After a successful query, stop the LiDAR publisher, wait more than 2 seconds, and query again: `lidar.active` must become false. Stop the bridge and verify it disappears from `live_interfaces`. Stored status remains historical, not proof of an online robot.

## Current limitations / next changes
This is intentionally a debugging milestone, not yet a natural-language tool. Core cannot autonomously invoke this ability from conversation. It does not validate localization accuracy, integrate Nav2, or enable motors. Add explicit TTL / pose transform freshness before exposing operational go/no-go checks to autonomous decisions. The current Core's read endpoints should be authenticated before production use with sensitive robot telemetry.
