# Bounded reverse recovery (2026-11-21)

This replaces Jarvis's former plan/follow/fail behavior tree with a **bounded
straight-backup recovery**. No LLM is involved in collision recovery.

When ComputePathToPose or FollowPath fails, the Nav2 RecoveryNode asks the
nav2_behaviors BackUp plugin to reverse 0.10 m at requested 0.05 m/s. The
plugin uses the local costmap and robot footprint to project collisions and
must reject obstructed recoveries. On a completed backup the pipeline replans
to the **same original goal**. At most two such recoveries are attempted per
NavigateToPose request; if reverse is unsafe, failed, or unavailable, Nav2
aborts instead of bypassing collision checking. No spin behavior is loaded.

## Hardware limitations and supervision

The PiCar-X is Ackermann-steered, not differential drive. Straight reverse
does not require a zero-radius spin. The lower LiDAR is forward-limited; rear
coverage primarily comes from the upper 360-degree LiDAR. Its effective
coverage, occlusion, and floor/trim hazards must be checked physically.
Nav2's costmap collision check is **not** independent safety supervision.
Prior measurements indicate the SunFounder motor interface may drive at about
0.16 m/s even when lower speeds are requested, so actual backup distance and
stopping overshoot must be measured before treating 0.10 m as a physical cap.

This change does **not** solve TF timestamp drops, local costmap conservatism,
stuck-wheel detection, or rear blind spots. No automatic arm, extra motor
timeout, or controller obstacle bypass is introduced.

## Deployment (operator at the Pi, robot parked and disarmed)

The code is Pi-side only. Railway Core does not need a restart for the
configuration to take effect. Verify no local changes before updating:

```bash
cd ~/jarvis
git status --short
git pull --ff-only
python3 -m unittest discover -s tests -p 'test_nav_recovery_config.py'
python3 -m py_compile ops/nav2/navigation.launch.py
source /opt/ros/jazzy/setup.bash
ros2 pkg executables nav2_behaviors | grep behavior_server
sudo systemctl restart jarvis-nav2.service
ros2 lifecycle get /behavior_server
ros2 lifecycle get /controller_server
ros2 lifecycle get /planner_server
ros2 lifecycle get /bt_navigator
ros2 action list -t | grep /backup
```

All four lifecycle nodes must be active before a goal is attempted.
If nav2_behaviors is absent, install the distribution's Nav2 behavior
package while disarmed and recheck. Do not arm on failed startup.

For a supervised test, first inspect both costmaps and rear upper-LiDAR
coverage, ensure no pet/person behind Jarvis, and keep physical motor cutoff
accessible. Start with a short safe free-space goal, then a low-risk goal
that naturally produces a controller abort. Confirm in the journal that
BackUp was invoked, actually displaced Jarvis a short distance, and the
same original goal was retried. Check that cancel/stop still interrupts
recovery and that a rear obstacle prevents backup. Do not deliberately
create a high-risk obstacle to trigger the test.

```bash
journalctl -u jarvis-nav2.service -n 200 --no-pager |
  grep -Ei 'backup|behavior_server|recover|collision|failed|abort'
```

## Rollback

If a recovery behaves unexpectedly, disarm immediately. Revert
`ops/nav2/point_to_point.xml` to the prior plan/follow-only tree (or
restore the previous repository commit), and restart
`jarvis-nav2.service` while disarmed. The behavior server can remain
running without an active recovery node; remove it from launch and
lifecycle for a full rollback.

## Next improvement

Add explicit recovery begin/end/failure diagnostics and verified rear
coverage gating before enlarging the recovery repertoire. A custom
Ackermann-specific reposition-and-replan action may eventually support
steered backing maneuvers, but is not implemented here.
