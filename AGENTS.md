# Jarvis — Project Context and Coding Guidance

_Last reviewed: 2026-11-18. Current code and actual Pi/Railway runtime observations take precedence over this handoff. This document separates demonstrated behavior, implemented-but-unverified changes, and roadmap ideas._

## 1. Mission and architectural invariant

Jarvis is a persistent, embodied AI assistant, initially using a SunFounder PiCar-X v2.0 with Raspberry Pi 4. The long-term goal is a capable agent that can converse, explore, understand places and objects, navigate, form useful memories, and act across multiple interfaces.

**One Core, one Jarvis.** Jarvis Core (Railway) owns identity, high-level reasoning, goals, conversations and memory. The PiCar-X, desktop, and any future robot are interfaces/bodies, not separate independent personalities. Edge components own sensors, motion, low-latency operations, and physical safety. Never make cloud access or an LLM necessary for emergency stopping. This separation is intended to make future robot hardware replacements practical.

Engineering priorities: incremental testable changes; ROS 2 for standard robot functionality; explicit verification of claims; narrow typed actions; controlled API/cloud costs; observability; and easy rollback.

## 2. Status snapshot — November 18, 2026

**Historical physical demonstrations (reported in development conversations):**
- Ubuntu 24.04 / ROS 2 Jazzy PiCar-X platform, dual RPLIDAR C1 scanners, RF2O odometry, SLAM Toolbox live mapping, and RViz visualization worked.
- Operator-guided mapping and coordinate-target autonomous navigation worked. The operator confirmed the robot could navigate to supplied coordinates.
- Frontier exploration progressed beyond visualization/planning into supervised physical autonomous exploration. Treat this as an experimental success, **not** validated unsupervised household navigation.
- Chained Agents SDK voice conversation, wake-word capture, Core interaction, and speech playback worked. Voice/vision integration was tested with two camera views.
- A profiling log from 2026-11-05 showed one legacy camera capture taking ~5.24 seconds. Slow capture was the immediate optimization target.

**Implemented in repository, but runtime state must be verified before claiming active:**
- Alpha/Bravo/Charlie selectable identity profiles in `jarvis_core/identity.py`, using `jarvis_identity*.md`, with one active profile persisted and loaded for each agent turn.
- Pi-local offline Vosk recognition for a limited set of control commands, cached local audio, once-per-boot voice readiness announcement; see `ops/LOCAL_VOICE_CONTROLS.md`.
- Two-view Agents SDK `inspect_environment` integration: explicit fresh photos at approximately -25°/+25°, Pi-to-Core image transfer, Core vision interpretation, and instrumentation. Image payloads are not intended to enter event/memory storage.
- Optional **persistent camera worker** built around isolated libcamera 0.3, a native C++ capture process, Python Unix socket, and `jarvis-camera.service`. This was the last development sprint, with final commits on 2026-11-06. **Physical Pi compilation, capture behavior, resource use, latency benefit and reboot persistence are not yet confirmed.** Old capture subprocess is the fallback when the worker socket is absent; see `ops/PERSISTENT_CAMERA.md`.
- Railway/Core attention routing, episodic/semantic memory and agent interfaces exist, but check runtime code and current data before asserting precise retention, behavior or completeness.

**Not established as finished:**
- Reliable autonomous operation without supervision; dedicated independent collision monitoring / hardware E-stop, complete obstacle coverage, map-localization recovery, and robust dynamic-obstacle handling.
- A verified save/reload/relocalization lifecycle for a durable household map across cold boots, with tested backups.
- Named semantic room regions and working voice-to-room navigation ("go to the kitchen").
- Persistent spatial/object tracking across time ("where were my keys 20 minutes ago?"), lifelong map maintenance, autonomous docking.
- Direct, permissioned self-development access to GitHub, Railway, and the Pi.

Do not treat deployed code, a successful unit test, or a working proof-of-concept as proof of physical reliability.

## 3. Repository topology and deployments

- `jarvis_core/`: cloud Core, identity, tools, memory, vision, conversations. Railway deployment is connected to this repository; verify current service/environment before use.
- `clients/voice/`: Pi-side wake/capture, voice interface, local commands/audio, environment-camera handling, native and Python camera worker.
- `body_services/picar/`: PiCar-X actions, motor hardware, ROS bridge and drive-controller code.
- `ops/nav2/`: custom Nav2 configuration, frontier detection/selection/exploration tools; read its README and actual launch/config files.
- `ops/systemd/`, `deploy/systemd/`: Pi services and deployment instructions.
- `tests/`: test coverage for voice, vision, identity, camera worker and ROS interfaces. Tests do not substitute for Pi hardware verification.

Do not assume the repository's top-level `README.md` is an overall current status page; it describes a specific Core attention phase. This handoff and specialized runbooks also need cross-checking against code. Avoid hard-coded credentials, hostnames and local paths in new code; preserve compatibility with existing deployments.

## 4. Hardware and ROS/navigation baseline

**Physical platform:** SunFounder PiCar-X v2.0 (Ackermann-like front steering), Raspberry Pi 4, Ubuntu 24.04.5 LTS aarch64, ROS 2 Jazzy; dual SLAMTEC RPLIDAR C1 sensors at different heights; camera on pan/tilt; Jabra Speak 710 USB audio. Ultrasonic sensor is **removed** and cannot be assumed available. Robot lacks wheel encoders.

**Reported LiDAR/ROS arrangement:**
- Lower scanner roughly 1.75 in above ground, forward about 6.5 in from rear axle and 0.375 in left; lower scan filtered to forward +/-90° on `/scan_lower`.
- Upper scanner roughly 3.75 in high and ~1.8125 in forward from rear axle; upper scan is generally full-circle (check current topic/remapping).
- Historical topics include `/scan_lower`, `/scan_lower_raw`, `/scan_upper_raw`, `/map`, `/odom_rf2o`, `/cmd_vel` and TF `map → odom → base_link` / laser frames. **Inspect active publishers and transforms** before changing anything; offsets and launch naming evolved during development.
- Mapping stack: `sllidar_ros2`, scan filtering, RF2O laser odometry, SLAM Toolbox. Navigation: Nav2 Smac Hybrid Ackermann-compatible planning / Regulated Pure Pursuit; bespoke PiCar-X `/cmd_vel` translation. Existing Nav2 configs use preliminary footprint/turning assumptions and warrant physical validation.
- `ops/nav2/README.md` records the staged navigation and frontier development, including the historical *early* disarmed-only phases. Later supervised exploration tests advanced further; do not infer the current implementation from only the first section of that evolving runbook.
- Service names used historically include `jarvis-mapping@shadowfax.service`, `jarvis-nav2.service`, `jarvis-drive@shadowfax.service`, `jarvis-bridge@shadowfax.service`, and `jarvis-control@shadowfax.service`. Confirm installed units on the Pi rather than assuming all are enabled.
- Current driving has a speed floor and steering calibration constraints; a commanded speed is not necessarily measured physical speed. Motor watchdogs cover command loss, **not** all obstacles. Drive service should start disarmed. A speech command is **not** a safety-rated emergency stop.

**Map persistence warning:** Saving occupancy map image/YAML is distinct from saving a SLAM Toolbox serialized pose graph. A historical explicit serialization + manual deserialization was tested; any automated resume/cold-boot recovery must be reverified before dependence on it. Do not overwrite a known-good map during experiments without a recoverable copy.

**Autonomy precautions:** Before physical tests inspect both sensor height coverage, rear visibility, costmaps, turning/footprint assumptions, velocity behavior, and the physical cutoff. Do not independently deploy unsafe drive behaviors based on model/tool instructions. Preserve a supervised, disarmed-first validation path for changes.

## 5. Voice, identity, camera and agent integration

**Voice:** The current development path is the Agents SDK chained pipeline, not the earlier Realtime POC: local "Hey Jarvis" wake → recorded utterance → Core speech-to-text / Agents SDK context and tool orchestration → generated response → Pi playback (Piper was used locally; other TTS experiments such as ElevenLabs occurred). Read deployed voice environment and `clients/voice/` before asserting which engine is currently active. Realtime and chained listener must not simultaneously own the audio device.

**Local controls:** `ops/LOCAL_VOICE_CONTROLS.md` defines offline commands (arm/disarm motors, reboot, power down) and explicit confirmation for dangerous actions. Any audible speaker may spoof these; they are not authentication. Cached local WAV acknowledgments avoid repeat synthesis; do not conflate local command recognition with free-form Core dialogue.

**Identity:** Alpha is original identity; Bravo and Charlie are separate identity files. Selection should change only the identity text for subsequent turns while preserving shared operational instructions, memory and tool constraints. Inspect `jarvis_core/identity.py` and tests before changing persistence or selection.

**Vision:** The tested inspection is two fresh angled images followed by Core interpretation; do not claim continuous scene recognition or object tracking. The November 5–6 camera sprint added detailed stage tracing, then an opt-in persistent camera worker for faster acquisition. Refer to `ops/PERSISTENT_CAMERA.md` for the exact build, status, CPU/RSS checks, service enablement, timed capture test, fallback and rollback instructions. Never replace the working isolated libcamera build with an incompatible system library. Worker idle captures are discarded, are not an automatic LLM request, and may still consume meaningful CPU/RAM.

**Cognition and memory:** Core's attention system can filter high-frequency routine sensor events before persistence or LLM processing, with goal subscriptions able to elevate otherwise unimportant events. Future visual object events, spatial regions and temporal facts should be structured and selectively retained—not raw sensor/video firehoses. Preserve one shared mind and auditable, permissioned actions.

## 6. Recommended immediate resumption sequence

1. **Establish live baseline:** on Pi inspect `git status`, current commit, service states and logs; compare to GitHub `main`. Check Railway health separately. Never blindly pull over local uncommitted changes.
2. **Finish November camera sprint:** verify isolated libcamera 0.3 worker build; install/start opt-in `jarvis-camera.service` only after validating compatibility; inspect socket health; run at least two real two-photo inspections; compare stage times and aggregate CPU/RSS; confirm camera availability after reboot; retain rollback. No Railway change is needed solely for worker installation.
3. **Revalidate physical autonomy:** disarmed ROS/Nav2 state inspection, then supervised brief navigation and frontier exploration with motor cutoff accessible. Check actual sensor coverage, costmaps, drive response, watchdog and TF before extending behavior.
4. **Validate durable map lifecycle:** backup, explicit save, shutdown, cold restart, map restore/localization, then ability to extend the map. Never sacrifice a known-good map.
5. **Add named regions and voice navigation:** persist semantic room labels bound to the map/frame, resolve a room to safe navigation pose(s), and route a spoken "go to kitchen" via a bounded asynchronous tool.
6. **Extend perception and memory carefully:** selective timestamped observations, confidence/staleness, spatial associations, and retrieval. Avoid indiscriminate recording.
7. **Consider bounded development tools** for GitHub/Railway/Pi only with human authorization, narrow permissions, cost caps, logging, rollback and kill switches.

## 7. Engineering instructions for agents / Codex

1. **Inspect before editing.** Read repository code, launch configs, tests, service files and recent commits; this document is context, not a substitute for source.
2. **Label evidence correctly.** Distinguish planned, committed, deployed, operator-demonstrated and physically validated. Never declare a robot behavior operational from the presence of a file.
3. **Keep increments small and testable.** Supply affected files, rationale, tests, deployment/rollback steps, and outstanding hardware assumptions.
4. **Do not casually rewrite a functioning ROS baseline.** Protect TF ownership, scan topics, RF2O, SLAM and motor control. Test in the actual ARM/ROS environment.
5. **Local safety overrides Core.** Bound speeds, durations, steering, and action lifetimes; fail safe on errors, stale commands or missing sensor health; keep explicit disarm / physical cutoff.
6. **Secrets stay out of Git.** Use environment variables/managed secrets; never commit credentials, tokens, private image/audio captures or personal data.
7. **Restrict autonomous actions and costs.** No recursive tool execution, production deployments, self-modifying code or significant recurring API/cloud work without explicit permission, audit logging, budgets and kill switches.
8. **Favor observability.** Trace IDs, bounded timeouts, structured logs and repeatable regression tests are preferable to opaque workflows.
9. **Do not conflate machines.** Desktop Linux, Railway Python services and Pi Ubuntu/ROS have distinct runtimes. Service/system paths are historical unless confirmed live.
10. **Preserve user work.** Check dirty working trees, avoid overwriting maps/data/config, and prefer reversible changes.

## 8. Useful starting references

- `ops/PERSISTENT_CAMERA.md`: latest camera optimization and opt-in worker installation.
- `ops/nav2/README.md`: navigation assumptions, service use and frontier milestone history.
- `ops/LOCAL_VOICE_CONTROLS.md`: offline local controls, permissions, cached audio.
- `deploy/systemd/README-agents-voice.md`: chained voice migration and boot announcement (historical details; check live TTS config).
- `HARDWARE_STATE.md`: physical hardware caveats, especially removed ultrasonic sensor.
- `CORE_INTERFACES.md`, `SELF_MEMORY.md`, `EVENT_DRIVEN_VISION.md`, `EMBODIED_CURIOSITY.md`: Core design/prototype histories; not all describe the current physical deployment.
