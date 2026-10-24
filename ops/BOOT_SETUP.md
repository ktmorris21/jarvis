# Jarvis: power-on startup (Ubuntu 24.04 / ROS Jazzy)

This setup starts only (1) the existing ROS mapping launch and (2) the **read-only** Core bridge. No motor/autonomy services are enabled. It does **not** claim mapping resume, auto-save, or automatic status polling.

## Install on Pi as shadowfax

Prerequisites: `~/jarvis` checked out from main, `~/ros2_ws/install/setup.bash` built, `ros2 launch jarvis_bringup mapping.launch.py` already tested, and the ROS bridge has already connected manually.

```bash
cd ~/jarvis
git pull --ff-only
sudo install -m 644 ops/systemd/jarvis-mapping@.service /etc/systemd/system/
sudo install -m 644 ops/systemd/jarvis-bridge@.service /etc/systemd/system/
sudo install -d -m 700 /etc/jarvis
sudo nano /etc/jarvis/bridge.env
```

Enter exactly two lines in the file (replace the URL and token with your actual values):

```ini
JARVIS_URL=https://jarvis-production-110e.up.railway.app
JARVIS_TOKEN=YOUR_TOKEN
```

Save, then secure it and enable:

```bash
sudo chown root:root /etc/jarvis/bridge.env
sudo chmod 600 /etc/jarvis/bridge.env
sudo systemctl daemon-reload
sudo systemctl enable jarvis-mapping@shadowfax.service jarvis-bridge@shadowfax.service
sudo systemctl start jarvis-mapping@shadowfax.service
sudo systemctl start jarvis-bridge@shadowfax.service
```

**Important:** stop any manually started mapping or bridge terminals *before starting the services*. Two copies can compete for the serial LiDAR device or overwrite the same WebSocket interface identity. Enabling services alone does not start them until boot; here we explicitly start them too.

## Inspect

```bash
systemctl status jarvis-mapping@shadowfax.service jarvis-bridge@shadowfax.service --no-pager
journalctl -u jarvis-mapping@shadowfax.service -n 50 --no-pager
journalctl -u jarvis-bridge@shadowfax.service -n 50 --no-pager
ros2 topic list
```

The bridge should log `ROS bridge connected to Core`. Check `/scan`, `/map`, and `/tf` topics. A running service doesn't guarantee live map data: query Core via `get_robot_status` as in `ROS_BRIDGE_V0_1.md`.

To reboot-test: `sudo reboot`; after reconnecting, inspect the commands above. To disable both: `sudo systemctl disable --now jarvis-mapping@shadowfax.service jarvis-bridge@shadowfax.service`.

## Operational decisions

- The bridge independently retries Railway connectivity. Mapping does not need internet access.
- A missing/stopped LiDAR may leave mapping services technically running; ROS status must be checked before relying on position.
- This uses the default `mapping.launch.py` invocation previously verified manually, **not** an unverified automatic restore. Saved-map resume is a separate milestone.
- Assumes checkout `/home/shadowfax/jarvis` and ROS overlay `/home/shadowfax/ros2_ws`. Edit templates and scripts if either moves.
- `bridge.env` contains a credential; **never commit it**. Keep temporary tokens out of shell history when possible. Rotate the temporary token later.
- The bridge currently responds to requests; it does **not** periodically update Core on its own.
