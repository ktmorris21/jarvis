# Navigation diagnostics — supervised baseline sprint (2026-11-19)

This milestone is **instrumentation only**. It does not modify motor watchdogs, Nav2 progress checks, LiDAR freshness thresholds, recovery policy, arm/disarm, speeds, or obstacle behavior.

## Data flow

- The Pi's drive controller and frontier detector publish discrete JSON events to ROS `/jarvis/diagnostics/events` (`std_msgs/String`).
- The Pi ROS bridge subscribes to those events and independently observes Nav2 `/navigate_to_pose/_action/status`, `/cmd_vel`, `/odom_rf2o`, `/scan`, `/scan_lower`, and `/map`.
- For each event, the bridge snapshots the most recent command, RF2O odometry, and telemetry ages, then forwards an authenticated `NAV_DIAGNOSTIC` WebSocket event to Core.
- Core logs a single structured `[NAV DIAG]` line to Railway. This deliberately **does not** invoke LLM, memory, or persistent Core events. Pi bridge journald also records `NAV_DIAG_LOCAL` events.
- The in-memory forwarding queue holds up to 300 records through temporary WebSocket disconnects, with a `NAV_DIAG_QUEUE_FULL` local warning on overflow. It is **not** durable across Pi bridge process restarts; keep Pi journald as a fallback.

Recorded event kinds include `motor_stop`, `motor_disarmed`, `motor_armed`, `drive_fault`, `exploration_started`, `exploration_halted`, `exploration_goal_sent`, `exploration_goal_failed`, `exploration_goal_succeeded`, and Nav2 goal accepted/executing/canceling/succeeded/canceled/aborted transitions. A motor watchdog stop is a `motor_stop` with reason `command watchdog expired`.

A snapshot shows the latest *command*, not necessarily the actual motor output. RF2O pose and speed are sensor-derived estimates, not wheel encoder readings. Telemetry ages are measured on the Pi at event receipt. A zero command may mean a routine Nav2 controller pause; the event reason and surrounding Nav2 events must be considered together.

## Deploy

1. Confirm latest GitHub Core commit deployed successfully to Railway **before** updating Pi. The old Core would route unknown diagnostics through its generic event handler, producing unnecessary persistent events.
2. On Pi, inspect `git status --short` in `~/jarvis`; preserve any local modifications. Then `git pull --ff-only`.
3. Validate syntax without starting motors:

```bash
cd ~/jarvis
python3 -m py_compile body_services/picar/ros_drive_controller.py body_services/picar/ros_bridge.py ops/nav2/frontier_detector.py jarvis_core/main.py
```

4. Restart the three affected **Pi** services in this order; consult the installed unit names if they differ:

```bash
sudo systemctl restart jarvis-drive@shadowfax.service
sudo systemctl restart jarvis-nav2.service
sudo systemctl restart jarvis-bridge@shadowfax.service
```

A drive-controller restart **disarms** motors, by design. Do not auto-arm on restart. Validate Nav2 lifecycle nodes are active, both costmaps and scanners fresh, operator cutoff accessible, then explicitly arm and conduct short supervised trials.

## Verify end to end

On Pi, monitor:

```bash
ros2 topic echo /jarvis/diagnostics/events std_msgs/msg/String
journalctl -u jarvis-bridge@shadowfax.service -f --no-pager | grep -E 'NAV_DIAG|bridge'
```

In Railway, filter deployment logs with `[NAV DIAG]`. An explicit arm/disarm or exploration start/stop should produce a corresponding event within seconds. If events appear on the ROS topic and Pi journal but not in Railway, inspect Pi bridge reconnection logs and the correct Railway deployment/environment. Do not rely on Railway log retention for indefinite historical storage.

Suggested supervised driving sequence: (1) explicitly arm/disarm once, (2) short coordinate goal, (3) longer coordinate goal, (4) frontier exploration, (5) normal operator stop, (6) reproduce the unexplained interruption if safe. For each failure note approximate time, observed motion, surface/obstacle, and whether the operator intervened. Avoid deliberately cutting the LiDAR feed during motion; any fault-injection should be performed with motors disarmed first.

## Rollback

Revert the instrumentation commits on the applicable branch, deploy Core and pull/restart Pi services. The diagnostics publish additional ROS messages but do not alter motion logic or safety thresholds.
