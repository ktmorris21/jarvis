# Jarvis point-to-point navigation sprint (ROS 2 Jazzy)

This first configuration runs Nav2 alongside the **existing** mapping service.
It does **not** start AMCL, another SLAM instance, a map_server, or a separate
velocity-smoothing topic. Nav2's controller publishes directly to `/cmd_vel`,
which Jarvis's drive controller ignores until explicitly armed.

Known robot state: RF2O /odom_rf2o (`odom -> base_link`); slam_toolbox
(`map -> odom`); upper `/scan` full circle and lower filtered
`/scan_lower`; 5cm SLAM map; PiCar-X wheelbase 0.09366m; observed
physical velocity ~0.16 m/s even at nominal low velocity requests.

## First deployment (motors DISARMED)

```bash
cd ~/jarvis
git status --short
git pull --ff-only
python3 -m py_compile ops/nav2/navigation.launch.py
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
sudo systemctl start jarvis-mapping@shadowfax.service
sudo systemctl status jarvis-drive@shadowfax.service --no-pager
ros2 launch ~/jarvis/ops/nav2/navigation.launch.py
```

Leave this launch running in its own terminal. It should configure/activate
`planner_server`, `controller_server`, and `bt_navigator` via the lifecycle
manager. Open a second terminal with the two `source` commands above and:

```bash
ros2 lifecycle get /planner_server
ros2 lifecycle get /controller_server
ros2 lifecycle get /bt_navigator
ros2 action list -t | grep -E 'navigate_to_pose|compute_path_to_pose'
ros2 topic list | grep -E '(global_costmap|local_costmap|plan)'
ros2 topic info /cmd_vel --verbose
```

For the initial path calculation check, leave the motors **disarmed**.
In RViz, use **2D Goal Pose** (confirmed working with Jarvis) to choose a nearby explored free area.
Inspect the generated plan and costmaps. A NavigateToPose request also attempts
to follow the plan, but disarming prevents any motor movement; expect the goal
to fail its progress check when the robot does not move. This is a *planning
smoke test*, not proof of safe driving.

Stop Nav2 with Ctrl-C in the launch terminal. This stops its /cmd_vel
publication and the independent drive watchdog stops the motors if needed.

## Initial modeling assumptions and limitations

- The 0.23m robot radius is a conservative preliminary circular envelope,
  **not** a measured front/rear relative footprint. Revisit before driving
  through tight spaces.
- The 0.20m minimum turning radius is a starting assumption based on a
  0.09366m wheelbase and nominal 30 degree steering cap. Real turning response
  remains to be measured.
- Smac Hybrid uses Reeds-Shepp forward/reverse planning (reverse penalty 2.0),
  with Regulated Pure Pursuit `allow_reversing: true` and `use_rotate_to_heading: false`.
  The behavior tree contains plan+follow only, with no automatic spin/backup
  recovery behavior.
- The 0.30m XY goal tolerance is deliberately forgiving. Final heading is not
  enforced strictly for the initial experiment.
- Lower and upper LiDAR feed both costmaps. Confirm costmaps visibly mark
  obstacles that exist at only one scanner's height.
- Regulated Pure Pursuit's collision projection uses **commanded**, not
  measured physical speed. Since SunFounder driving has a ~0.16m/s floor,
  its stopping projection cannot be trusted as a standalone obstacle stop.
  The drive watchdog stops on absent commands, *not* obstacles.
- No dedicated Nav2 Collision Monitor is deployed yet and there is no
  independent hardware emergency stop in this code. Only conduct initial
  physical motion with clear floor, operator present, and accessible physical
  motor cutoff.
- This launch is intentionally run manually during the first sprint, rather
  than installed as a new systemd service before verification.

## Source

The setup uses the Jazzy Nav2 controller, planner, and BT navigator nodes.
It intentionally does not run the stock `nav2_bringup/navigation_launch.py`,
which remaps controller output to `cmd_vel_nav` for smoothing.

## Reverse navigation validation (after enabling Reeds-Shepp)

The existing `ros_drive_controller.py` maps negative `/cmd_vel.linear.x` to
`PiCarHardware.drive("backward", power)` and computes steering from `omega / v`.
That is compatible with reverse Ackermann motion, but the sign, speed, stopping
behavior, and reverse obstacle coverage need real-hardware validation.

1. Keep the motors disarmed. `git pull --ff-only`, restart
   `jarvis-nav2.service`, and confirm planner/controller/BT lifecycle ACTIVE.
2. Inspect a Reeds-Shepp route with RViz **2D Goal Pose**. For a pure backing
   test, choose a free-space goal behind Jarvis with a similar heading; monitor
   `/cmd_vel` for negative `linear.x` while disarmed.
3. Only if the rear is clear in the *costmap* and physically, arm for a short,
   supervised reverse drive with immediate access to motor disarm/power cutoff.
   The lower LiDAR has forward-limited coverage; rear detection relies mainly
   on the upper LiDAR. Do not assume the 0.23 m circular robot footprint covers
   protrusions or that velocity scaling perfectly matches physical speed.
4. For rollback: revert the two options to `DUBIN` and `allow_reversing: false`,
   remove the optional `reverse_penalty`, then restart `jarvis-nav2.service`.



## Frontier exploration sprint — milestone 1: read-only detection

The existing `jarvis-nav2.service` now also launches
`ops/nav2/frontier_detector.py`. It subscribes to the live
`/map` OccupancyGrid from slam_toolbox and publishes RViz
`visualization_msgs/MarkerArray` on:

```text
/jarvis/exploration/frontiers
```

**No motor command, Nav2 goal, or Agent tool is created in milestone 1.**
Orange spheres indicate one representative observed free cell in each
frontier cluster; turquoise points show the free/unknown boundary.
These are visualization candidates, NOT vetted Ackermann-reachable
Nav2 destinations. Clusters smaller than six cells are ignored; up to
40 largest are displayed. Frontier cells require observed free occupancy
at most 20 and a four-connected unknown neighbor. A scan of the grid
runs no more often than once per three seconds and only on new map data.

### Deploy (no extra services or long-lived terminals)

```bash
cd ~/jarvis
git pull --ff-only
python3 -m py_compile ops/nav2/frontier_detector.py ops/nav2/navigation.launch.py
sudo systemctl restart jarvis-nav2.service
sudo systemctl status jarvis-nav2.service --no-pager
```

RViz: **Add -> By topic -> /jarvis/exploration/frontiers -> MarkerArray**
(or add a MarkerArray display and set the topic yourself).
Use **Fixed Frame = map** for frontier markers in map coordinates.
An RViz TF display issue can hide markers even if the topic is publishing;
read-only markers never change the planner or costmaps.
The marker publisher is transient-local, so opening RViz later should
receive the most recent marker batch.

For occasional troubleshooting (no persistent terminal needed):

```bash
journalctl -u jarvis-nav2.service -n 60 --no-pager | grep -Ei 'frontier|error|traceback'
```

Next increment: plan-checked candidate staging points, a bounded
NavigateToPose exploration loop, explicit stop/cancel and safety gating,
then asynchronous Agent SDK tools. The actual frontier detector in this
milestone does not command Jarvis to drive.


## Frontier exploration sprint — milestone 2A: plan preview (motors DISARMED)

The existing frontier detector now evaluates staging points `~0.35m` back
from frontier boundaries, requiring a `0.23m` known-free disk around each
candidate. Every `20s` at most, it checks up to five candidates via
Nav2's `/compute_path_to_pose` action using the existing Smac Hybrid
Reeds-Shepp `GridBased` planner. Candidates are rejected if they do not
yield a successful nonempty path. A short path is preferred, with a
modest bonus for larger frontier clusters.

**This is still strictly planning only.** The detector never invokes
NavigateToPose, publishes velocity, or arms the robot. Planner success
means Nav2 found a path under its current modeled constraints, **not**
proof of safe real-world traversal.

### One-service deployment

```bash
cd ~/jarvis
git pull --ff-only
python3 -m py_compile ops/nav2/frontier_detector.py
sudo systemctl restart jarvis-nav2.service
```

After restart confirm the previously problematic Nav2 lifecycle nodes
are all `active [3]`. If not, inspect `journalctl -u jarvis-nav2.service`
before trusting the route preview.

In RViz with Fixed Frame `map`, retain milestone 1 frontiers and add:

- **MarkerArray** topic `/jarvis/exploration/selection`:
  a **blue sphere** at the currently preferred known-free staging point.
- **Path** topic `/jarvis/exploration/selected_path`:
  Nav2's returned route to that point.

The detector logs `Preview best frontier...` or `Preview: no valid
Nav2 path...`. Candidates are reevaluated periodically as the live map
changes. Selection visualization may briefly clear while recomputing.

A missing blue marker can be legitimate if no candidate passes the
known-free staging or Nav2 path checks. Do not reduce footprint,
inflation, or obstacle detection merely to force a route through.

The next increment enables bounded supervised goal execution and
cancellation, after hard-stop safety is validated. Voice/Agent SDK
exposure comes later; neither is part of this increment.


## Frontier exploration sprint — Milestone 2B: supervised autonomous driving

**Disabled by default.** Nothing begins driving on a clean reboot or Nav2
restart. Milestone 2A frontier/route preview remains available while idle.

Only the three requested safeguards are included:

1. Explicit ROS Trigger services to start, stop, and check status:
   `/jarvis/exploration/start`, `/jarvis/exploration/stop`,
   `/jarvis/exploration/status`.
   Stop requests Nav2 goal cancellation and motor **disarm** through the
   existing `/jarvis_drive/set_armed` SetBool service. If the disarm
   service is unavailable, use the physical motor cutoff.
2. On Nav2 goal success, return to frontier selection when new map data
   arrives. On failure, blacklist staging points within 0.40 m of the
   failed point for the session, and select another. Three consecutive
   navigation goal failures stop the session. A successful goal resets
   the consecutive-failure count. With no remaining eligible/reachable
   frontiers, exploration stops.
3. Stop/cancel/disarm when both required live LiDAR inputs aren't fresh
   (each scan must be within 2 seconds), the `map -> base_link` transform
   is older than 1 second, or map messages go more than 20 seconds without
   an update. The local detector checks health every 0.25 seconds.
   The last condition detects loss of map publication, not whether
   SLAM is accurately localized.

**Not included**: exploration duration cap, independent collision monitor,
rear collision recovery, automatic map saving, automatic motor arming,
Agent SDK tool/voice command, and a separate safety supervisor.
The existing drive watchdog remains active. Path planning and Nav2's
controller use both upper and lower LiDAR costmap observations.

### Deploy under the existing Nav2 service

```bash
cd ~/jarvis
git pull --ff-only
python3 -m py_compile ops/nav2/frontier_detector.py
sudo systemctl restart jarvis-nav2.service
```

**Do not arm or start until** the controller, planner, and BT navigator
are all `active [3]` and both costmaps have updated. We previously saw
lifecycle initialization occasionally fail on ordinary service restart.
Use RViz to verify the preview route and clear the test area.

### Run supervised exploration (one terminal, no new daemon)

Arm the motors **separately** using your existing confirmed offline
voice command or existing SetBool service. The exploration controller
intentionally does not arm them:

```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash

ros2 service call /jarvis_drive/set_armed std_srvs/srv/SetBool "{data: true}"
ros2 service call /jarvis/exploration/start std_srvs/srv/Trigger "{}"
```

The explorer immediately begins choosing and executing frontier goals.
Monitor the robot in person. It can continue indefinitely until frontiers
are exhausted, a health/failure condition stops it, or you stop it.

To stop from the same terminal (or another available shell):

```bash
ros2 service call /jarvis/exploration/stop std_srvs/srv/Trigger "{}"
```

To read progress:

```bash
ros2 service call /jarvis/exploration/status std_srvs/srv/Trigger "{}"
```

If any software cancellation fails, use the existing physical motor
power cutoff. A service call response confirms the request was received,
**not** that Nav2 has already acknowledged cancellation and the motors
have physically stopped. Voice control through the Agent SDK is a future
increment; no new model-facing movement tool is exposed yet.

### Observability

The existing RViz selection and selected-path topics are unchanged.
Status reports `mode`, `goals_completed`, `consecutive_failures`,
and the most recent reason. Live logs are in the same systemd unit:

```bash
journalctl -u jarvis-nav2.service -n 80 --no-pager | grep -Ei 'exploration|frontier|goal|error'
```

This code has been committed but has not been hardware-tested by the
assistant; first run should be short, supervised, and in a clear area.
