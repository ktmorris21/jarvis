# Jarvis — Project Context and Coding Guidance

_Last updated: 2026-10-23. This document is a project handoff and may lag behind the actual code. Repository code, configuration, and tests are authoritative for implementation details._

## 1. Mission

**Jarvis** is an experimental embodied AI assistant built around a **SunFounder PiCar-X v2.0** mobile robot with a **Raspberry Pi 4**. The aim is not merely remote driving or a voice chatbot: the long-term goal is a persistent, curious agent that can explore an indoor environment, develop and maintain a map, recognize important places and objects, navigate autonomously, converse, and accumulate useful memories over time.

The intended design has **one logical intelligence (the Jarvis Core)**, accessible from multiple clients (robot, desktop/laptop, potentially others). The physical robot is one embodiment/client of the same system. Do not implement a separate independent LLM personality or long-term memory silo on the Pi unless explicitly requested.

**Design priorities:** incremental, testable milestones; reuse ROS 2 capabilities where appropriate; edge-local safety and low-latency control; understandable and maintainable code; controlled operational/API costs; and a clear separation between tested functionality and future ideas.

## 2. Architecture: Current vs Intended

### Intended division of responsibility

| Layer | Intended responsibilities | Status |
|---|---|---|
| **Jarvis Core (cloud)** | Persistent identity, interaction orchestration, goals, episodic/semantic memory, reasoning, tool invocation, later agentic workflows | Core architecture/service exists; individual capabilities need repository verification |
| **Robot edge (Raspberry Pi)** | Sensors, ROS 2 nodes, local mapping/localization/navigation, low-latency motor control, collision avoidance, audio I/O, local failsafes | LiDAR + mapping stack working; integrated autonomous navigation/safety not yet established |
| **Desktop/other clients** | Interact with the same Core rather than spawning a separate Jarvis mind | Part of project architecture; verify current client functionality in code |
| **LLM/API layer** | Conversation, higher-level decisions, semantic interpretation of camera observations; potentially structured tool calls | Future/evolving integration; do not assume complete implementation |

The Core has been hosted on **Railway** (historically identified as `jarvis-production-110e`). Do not hardcode a deployment hostname, secret, or environment-specific endpoint: inspect deployment configuration. The Core has used the concepts of *attention*, *episodic memory*, and *semantic memory*, with *procedural memory* planned. A historical memory cap of 12 has been mentioned; **verify the current code before relying on it**.

**Important separation:** ROS 2 should implement or coordinate robotic functions, while the LLM handles semantic understanding, interaction, and strategic goals. Cloud connectivity should never be required for emergency braking or other immediate physical safety decisions.

### Conceptual data flow (target)

```text
Human / desktop / mobile / robot interaction
                     |
                     v
              Jarvis Core (Railway)
       goals, memory, dialogue, orchestration
                     |
               tool/action API
                     |
                     v
            Raspberry Pi edge agent
          ROS 2 / sensors / actuators
              /               \
    perception + SLAM       safety + motion
          |                       |
   LiDAR, future camera       PiCar-X motors
```

This is **an architectural direction, not proof all interfaces exist today**.

## 3. Robot Hardware

| Component | Configuration / known facts |
|---|---|
| Chassis | SunFounder **PiCar-X v2.0**, steering-servo car |
| Compute | Raspberry Pi 4, 64-bit |
| OS | **Ubuntu 24.04.5 LTS, aarch64** (migrated from Debian 11 Bullseye) |
| ROS | **ROS 2 Jazzy Jalisco** |
| LiDAR | **SLAMTEC RPLIDAR C1**, mounted for full 360° scanning; firmware previously reported 1.02, hardware revision 18 |
| Robot motors/servos | SunFounder PiCar-X / Robot HAT Python control; movement and steering verified working on Ubuntu |
| Camera | Intended for future semantic vision; do not assume camera ROS pipeline is operational |
| Ultrasonic distance sensor | Previous unit broken/removed; replacement planned; **do not assume operational** |
| Audio | Earlier USB Jabra-style speakerphone/microphone worked for exploratory voice tests; smaller audio hardware and a microphone array have been considered, not established as complete integration |
| Charging | Robot HAT charges through a **side-mounted USB-C port**; autonomous charging dock is only a future concept |

Physical dimensions measured previously: chassis approximately **9.75 in long × 5.5 in wide × 6.125 in high**; LiDAR center approximately **4.5625 in behind the front edge**, laterally centered; LiDAR scan plane approximately **5.875 in above the ground**. Recheck offsets and reference frames before encoding precise transforms.

**Mechanical issue:** stock wheels have difficulty crossing some hardwood/tile transition strips. The robot may turn/spin along the trim instead of traversing it. Higher-traction tires are under consideration. Navigation code must not assume every apparent 2D traversable passage is physically crossable.

## 4. ROS 2 / SLAM — Most Recently Confirmed Working

The LiDAR and mapping system is a key active area of development.

**Confirmed historical working behavior:**

- RPLIDAR C1 publishes live scans on **`/scan`**.
- **SLAM Toolbox** maps scans, publishing **`/map`**, viewable in RViz 2.
- TF frame setup has been debugged; current mapping bringup uses a static transform from **`base_link` to `laser`** (check live code for offsets and naming).
- **RF2O** laser odometry is included in the more recent bringup arrangement.
- PiCar-X manual drive/steering works while observing mapping output.
- RViz 2 has been run on a Linux desktop via Docker/X11 for remote visualization.
- Saving a SLAM Toolbox **serialized pose graph**, then explicitly calling **`/slam_toolbox/deserialize_map`**, has successfully restored previously explored areas into RViz after a restart.

### Recent mapping bringup layout

The following path was reported on the **Pi** (verify that it exists and matches the current checkout):

```text
~/ros2_ws/src/jarvis_bringup/launch/mapping.launch.py
```

This launch file orchestrates the RPLIDAR C1, static transform (`base_link` → `laser`), RF2O, and SLAM Toolbox. It has supported a `mapper_config:=...` launch argument.

A **bringup v0.2** was subsequently proposed/provided with two modes:

- **`fresh`** — new mapping session.
- **`resume`** — reload the serialized SLAM pose graph from `~/jarvis_maps/house_v1/house.posegraph` automatically at startup.

**Verification boundary:** manual `/slam_toolbox/deserialize_map` restoration is confirmed; the automated `resume` bringup was supplied as a change but must be tested/confirmed against the actual checked-in files and a cold restart before calling it verified. Likewise, verify the exact launch arguments and executable names from the repository rather than assuming them.

### Previously used services / commands

```bash
# Serialize mapping state (the pose graph, not merely an occupancy-map image)
ros2 service call /slam_toolbox/serialize_map \
  slam_toolbox/srv/SerializePoseGraph \
  "{filename: '$HOME/jarvis_maps/house_v1/house'}"

# Save occupancy map output separately when needed
ros2 service call /slam_toolbox/save_map \
  slam_toolbox/srv/SaveMap \
  "{name: {data: '$HOME/jarvis_maps/house_v1/house'}}"
```

**Critical distinction:** An occupancy map (`.pgm` / `.yaml`) is not a substitute for a SLAM Toolbox **serialized pose graph** (`.posegraph` and related data) when resuming an online mapping session. Saving a `.pgm` alone does not restore the active SLAM session. Do not introduce automatic periodic overwriting of the canonical good map without a tested recovery/backup strategy. Explicit-only saving was part of the v0.2 design.

**Coordinate-frame caveat:** Earlier experiments used `base_footprint`; later bringup references `base_link`. Inspect actual active TF tree, launch files, and configs before editing; avoid duplicate or contradictory transform publishers. Expected higher-level tree is conceptually `map → odom → base_link → laser`, but the precise broadcasters are implementation-dependent.

### Known ROS / vehicle issues

- LiDAR / ROS startup, TF relationships, and RViz remote rendering required troubleshooting; avoid gratuitously replacing the functioning configuration.
- Strong steering bias was observed; nominal straight-ahead command required approximately **−12°**, with calibration previously set around **−15°**. Right steering was limited to about **+15°** in one test setup. Verify current calibration in code and on hardware.
- The platform is **Ackermann-like steering**, not a differential-drive robot. Motion and navigation controllers must respect this.
- Mapping works; **do not assume** robust pose recovery, autonomous path planning, obstacle avoidance, automatic exploration, docking, or waypoint navigation is working.
- Dynamic objects (people, dogs, doors) can appear in LiDAR scans and occupancy maps. Handling transient obstacles and map changes remains a future design concern.

## 5. Vision, Audio, and Cognition Roadmap

The following are **planned/under discussion**, not claimed to be working:

**Vision and semantic mapping**

- ROS 2 camera integration, likely publishing `sensor_msgs/Image` (often `/camera/image_raw`).
- On-Pi vision candidates include OpenCV and a lightweight object detector, subject to Raspberry Pi resource tests; inference backends such as ONNX Runtime, TensorFlow Lite, or NCNN are possibilities, not selected dependencies.
- Fuse visual detections with LiDAR-derived geometry to identify objects, people, pets, and room types.
- Occasionally send selected still photos to a multimodal LLM for higher-level interpretation, e.g., "this appears to be a kitchen," enriching geometric maps with semantic labels.
- Respect privacy and avoid indiscriminate image capture/upload.

**Navigation / autonomy**

- Establish reliable odometry and localization, persistence of maps, navigable costmaps, steering-compatible planning/control, local obstacle detection, and recovery behaviors.
- Explore ROS 2 navigation components (e.g., Nav2) rather than reimplementing standard robotics algorithms, but account for the PiCar-X steering geometry and hardware constraints.
- Local safety supervisor should retain authority to stop motion on unsafe conditions, disconnected Core, or bad sensor health.
- Longer-term: exploration/curiosity, named destinations, semantic place memory, autonomous charging dock.

**Audio**

- Compact USB speakerphone with acoustic echo cancellation (AEC), or carefully integrated separate microphone array/speaker.
- Voice activation options explored: wake word versus physical USB push-to-talk button.
- Avoid two independent listening/speaking loops competing for the audio device. Confirm device identifiers at runtime rather than hardcoding ALSA card numbers; a historical test used `plughw:5,0`.

**LLM / persistent memory**

- Jarvis should use the same Core identity and memory regardless of client.
- A two-stage context retrieval approach has been discussed: first determine relevant memory/time horizons, then construct context for the user-visible answer.
- OpenAI agent orchestration/session features are **candidates**, not a drop-in replacement for persistent episodic, semantic, spatial, and procedural memory.
- Spatial memory should eventually link ROS map frames/locations with language-level concepts (rooms, objects, routes).
- Structured, auditable tools are preferable to unconstrained natural-language commands for moving the robot or modifying infrastructure.

## 6. Engineering Conventions for Codex

1. **Inspect before changing.** Read existing repository structure, dependencies, scripts, ROS package manifests, launch files, parameters, and deployment configs. This handoff is not a substitute for code inspection.
2. **Distinguish known from proposed.** Do not silently present roadmap items as implemented behavior or invent missing services/topics/APIs.
3. **Keep changes scoped.** Prefer one clearly testable increment per pull request, with a summary of changed files, design rationale, test instructions, and unresolved assumptions.
4. **Preserve the working mapping baseline.** Avoid unrequested rewrites of LiDAR drivers, TF tree, RF2O, or SLAM Toolbox config. If refactoring bringup, compare topic graph and transforms before/after.
5. **Honor safety boundaries.** Robot-local code has final authority to stop movement. Provide explicit stop/timeout behavior, bounded speeds, and safe states when connections or sensors fail. Never let an LLM directly bypass these limits.
6. **Do not embed secrets.** Credentials, API keys, deployment tokens, and personal data belong in environment variables or secrets management; never source-control them.
7. **Control cost and autonomy.** Before enabling recursive tool use, self-modifying code, or cloud/API jobs, require enforceable spending/usage limits, execution permissions, isolation, logging, and a manual override/kill switch. A surprise bill in the low hundreds is tolerable; runaway bills in the tens of thousands are not.
8. **Prefer simplicity and observability.** Use familiar Python/ROS 2 patterns, logging, clearly named topics/services, small components, reproducible commands, and tests. Avoid introducing extra frameworks solely for novelty.
9. **Do not assume the developer environment equals the Pi.** Local development has involved a Linux Mint Debian Edition laptop, remote SSH, Dockerized RViz, and Ubuntu/ROS on the ARM Pi. Test deployment-specific changes in the correct environment.
10. **Do not require operator-specific paths.** Paths in this document are historical examples; make working directories, map names, launch arguments, and endpoints configurable where appropriate.

## 7. Suggested Immediate Sequence

1. **Audit current state:** enumerate actual GitHub repository structure and compare it against the baseline in this file. Identify which functions run on Core vs Pi, and which launch files are versioned.
2. **Verify mapping resume:** demonstrate fresh session → explore → explicit serialize → shutdown/restart → resume → old map retained while new scans can extend it. Confirm restart behavior and localization assumptions. Do not overwrite the known-good saved map during testing.
3. **Stabilize robot motion/odometry:** confirm steering calibration, command interface, velocities, timestamps, frame convention, and RF2O quality.
4. **Add local motion safety and obstacle handling** before granting the Core autonomy over movement.
5. **Introduce navigation incrementally:** controlled goals, path planning, collision recovery, then exploration and semantic map enrichment.
6. **Integrate Core-to-robot actions** using narrow, typed interfaces with acknowledgments, timeouts, and safety checks.
7. **Expand modalities** (audio, camera, LLM semantic interpretation) only once their resource and integration constraints are understood.

This is a prioritization proposal, not a commitment that all items belong in the next development task.

## 8. Questions Codex Should Resolve from the Repository

- What exact repositories/packages contain the cloud Core, desktop client, and robot edge software?
- Which `mapping.launch.py` version is present, and are `fresh` / `resume` modes checked in?
- Which node owns each TF (`map→odom`, `odom→base_link`, `base_link→laser`)? Are timestamps synchronized and frames consistent?
- How is saved map state stored, backed up, loaded, and validated?
- What code currently owns manual motor control and emergency stopping?
- Are navigation, camera, ultrasonic, voice, and Core API interfaces already partially implemented?
- Are there tests, CI checks, and reproducible deployment instructions?

**Do not fill unknowns by guessing. Report them, inspect code, and propose bounded next steps.**
