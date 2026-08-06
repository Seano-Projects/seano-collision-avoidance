# SEANO Collision Avoidance

Vision-based collision-avoidance and guarded field-test support for the SEANO Unmanned Surface Vehicle (USV).

This repository contains a ROS 2 Humble workspace for camera-based obstacle perception, collision-risk evaluation, avoidance-command generation, runtime monitoring, structured logging, guarded thruster testing, and controlled AUTO-to-MANUAL takeover experiments.

![SEANO collision avoidance system overview](docs/assets/seano_ca_system_overview.png)

## Current Configuration

| Category | Current configuration |
|---|---|
| Platform | NVIDIA Jetson Orin |
| Middleware | ROS 2 Humble |
| Perception | Camera stream and YOLOv8 detector |
| Risk inputs | Proximity, centrality, approach, bearing consistency, and visual time-to-collision |
| Avoidance commands | Hold course, slow down, turn port, turn starboard, and stop |
| MAVROS | Reuses the external MAVROS instance |
| RC override publisher | `/usv/thruster` must remain the sole publisher to `/mavros/rc/override` |
| Repository RC bridge | Disabled in the current pool-test entry points |
| Field-test ROS domain | `ROS_DOMAIN_ID=0` |
| Runtime output | `runtime_artifacts/<RUN_ID>/` |
| Default profile | Safe preview baseline with hardware output disabled |

## TensorRT Inference

The current operational profiles use a locally generated TensorRT engine:

~~~text
yolov8n.engine
FP16
416 × 416
batch 1
~~~

The engine is generated directly on the target Jetson because TensorRT engine compatibility depends on the GPU, CUDA, and TensorRT versions.

The tracked `yolov8n.pt` file remains the source model. The generated `yolov8n.engine` file is excluded from Git and must exist locally at:

~~~text
seano_ca_ws/src/seano_vision/models/yolov8n.engine
~~~

The three operational profiles explicitly select this TensorRT engine with `imgsz=416` and FP16 inference.

## Operating Profiles

The profiles below are separate and must not run at the same time.

| Profile | Entry point | Purpose | Physical output |
|---|---|---|---|
| Safe preview baseline | `seano_ca_ws/run_pool_existing_control_path.sh` | Perception, risk evaluation, command preview, HUD, and logging | Disabled |
| Guarded thruster test | `seano_ca_ws/run_pool_thruster_hardware_test.sh` | Limited MANUAL-mode physical thruster test through the existing external control path | Possible after all gates pass |
| Guarded AUTO takeover | `seano_ca_ws/run_pool_auto_takeover_test.sh` | Controlled AUTO-to-MANUAL takeover and return-to-AUTO experiment | Possible after all gates pass |

The safe preview baseline is the default profile for development and data collection.

The guarded hardware entry points are experimental field-test tools. They do not replace the external production arbitration contract described in `docs/THRUSTER_ARBITRATION_INTERFACE_REQUIREMENTS.md`.

## Safety Boundary

The current pool-test scripts reuse systems that already operate outside this repository:

- the existing MAVROS instance;
- the existing `/usv/thruster` node;
- the external vehicle-control and startup services;
- the external MQTT infrastructure.

The scripts do not start another MAVROS instance.

The current pool-test entry points do not launch `mavros_rc_override_bridge_node`.

This repository must not create a second publisher on `/mavros/rc/override`.

Before a field run:

- confirm the FCU is connected;
- confirm the FCU is disarmed during preflight;
- confirm `/usv/thruster` is the sole RC override publisher;
- confirm no other collision-avoidance profile is active;
- keep operator authority available;
- keep the tether and emergency stop ready;
- use an exclusive test window;
- keep the test area clear.

Stop the active profile with `Ctrl+C` in the terminal that started it.

## Workspace Setup

Run these commands after opening a new terminal or restarting the Jetson:

~~~bash
cd ~/resource_git/seano-collision-avoidance2/seano_ca_ws

source /opt/ros/humble/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=0
~~~

The workspace is intentionally not sourced automatically from `~/.bashrc`, so it does not affect unrelated ROS workspaces.

## Profile 1: Safe Preview Baseline

This is the default and safest profile.

~~~bash
cd ~/resource_git/seano-collision-avoidance2/seano_ca_ws

source /opt/ros/humble/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=0

./run_pool_existing_control_path.sh
~~~

The script fixes the following safety configuration:

~~~text
dry_run=true
hardware_output_enabled=false
use_mavros=false
use_rc_override_bridge=false
mqtt_publish_enabled=false
~~~

It runs perception, obstacle detection, risk evaluation, avoidance-command preview, HUD output, and event logging without transmitting physical collision-avoidance commands.

If the FCU is in RTL, the script requires an explicit dry-run confirmation. It will not allow an armed baseline run.

Default HUD topic:

~~~text
/ca/debug_image
~~~

Example HUD URL:

~~~text
http://<JETSON_IP>:8080/stream?topic=/ca/debug_image
~~~

## Profile 2: Guarded Thruster Hardware Test

> Warning: physical thrusters may move.

This profile is intended only for supervised first-stage pool testing.

The operator performs the MANUAL-mode selection and arm procedure. The script does not call `set_mode` and does not arm or disarm the FCU.

### Default first-test limits

| Parameter | Default |
|---|---:|
| Maximum throttle | 10% |
| Maximum steering | 15% |
| Maximum continuous motion | 2 seconds |
| Startup grace period | 8 seconds |
| Required FCU mode for motion | MANUAL |

### Dry check

~~~bash
./run_pool_thruster_hardware_test.sh --dry-check
~~~

The dry check starts no ROS node, opens no MQTT connection, and publishes no command.

### Read-only preflight

The credential file must use an absolute path outside this repository.

~~~bash
SEANO_MQTT_ENV_FILE=/absolute/path/to/system.yaml \
./run_pool_thruster_hardware_test.sh --preflight-only
~~~

Required result:

~~~text
Ready for guarded operator procedure: true
~~~

### Real guarded run

Set the confirmations only after each condition has been physically verified:

~~~bash
export CA_HARDWARE_TEST_ENABLE=yes
export CA_SHARED_MQTT_TEST_CONFIRM=yes
export CA_TETHER_CONFIRMED=yes
export CA_EMERGENCY_STOP_CONFIRMED=yes
export CA_EXCLUSIVE_TEST_WINDOW_CONFIRMED=yes
~~~

Run:

~~~bash
SEANO_MQTT_ENV_FILE=/absolute/path/to/system.yaml \
./run_pool_thruster_hardware_test.sh
~~~

Enter the exact confirmation:

~~~text
TYPE: ENABLE GUARDED THRUSTER TEST
~~~

Default HUD topic:

~~~text
/ca/hardware_test/debug_image
~~~

HUD availability is required before physical motion is permitted. If the HUD server is unavailable, the guarded runtime remains blocked or falls back to preview-only behavior.

## Profile 3: Guarded AUTO Takeover

> Warning: this profile can request FCU mode changes and command physical movement after all safety gates pass.

This procedure tests:

~~~text
AUTO -> MANUAL takeover -> AUTO restoration
~~~

It reuses the external MAVROS instance and `/usv/thruster`. It does not start MAVROS and does not launch an RC override publisher from this repository.

### Dry check

~~~bash
./run_pool_auto_takeover_test.sh --dry-check
~~~

The dry check starts no ROS node, opens no MQTT connection, publishes no command, and sends no FCU mode request.

### Read-only preflight

~~~bash
SEANO_MQTT_ENV_FILE=/absolute/path/to/system.yaml \
./run_pool_auto_takeover_test.sh --preflight-only
~~~

Required result:

~~~text
Ready for guarded AUTO takeover procedure: true
~~~

Preflight checks include:

- `ROS_DOMAIN_ID=0`;
- valid MQTT credentials with TLS;
- FCU connected and disarmed;
- `/usv/thruster` as the sole RC override publisher;
- MAVROS RC subscriber availability;
- `/mavros/set_mode` availability;
- no conflicting collision-avoidance runtime;
- validated mapping, timing, and motion limits.

The operator must select AUTO before arming.

### Real guarded run

Set the confirmations only after each condition has been physically verified:

~~~bash
export CA_AUTO_TAKEOVER_TEST_ENABLE=yes
export CA_SHARED_MQTT_TEST_CONFIRM=yes
export CA_TETHER_CONFIRMED=yes
export CA_EMERGENCY_STOP_CONFIRMED=yes
export CA_EXCLUSIVE_TEST_WINDOW_CONFIRMED=yes
export CA_MODE_TAKEOVER_CONFIRMED=yes
~~~

Run:

~~~bash
SEANO_MQTT_ENV_FILE=/absolute/path/to/system.yaml \
./run_pool_auto_takeover_test.sh
~~~

Enter the exact confirmation:

~~~text
TYPE: ENABLE GUARDED AUTO TAKEOVER TEST
~~~

Default HUD topic:

~~~text
/ca/auto_takeover/debug_image
~~~

Example HUD URL:

~~~text
http://<JETSON_IP>:8080/stream?topic=/ca/auto_takeover/debug_image
~~~

## Runtime Safety States

The guarded runtime uses fail-closed states to prevent motion before the complete control path is ready.

Typical states include:

- `STARTING`;
- `WAITING_FOR_CA_READY`;
- `WAITING_FOR_OPERATOR_ARM`;
- `ARMED_FOR_TEST`;
- `READY_FOR_OBSTACLE_TEST`;
- `MOTION_ACTIVE`;
- `PREVIEW_ONLY`;
- `ABORTED`.

Motion remains blocked when required data is stale, MQTT is unavailable, the FCU state is invalid, another publisher or runtime is detected, the HUD gate fails, or another safety condition is not satisfied.

## Main Runtime Components

### Perception and decision path

- `camera_node`
- `detector_node`
- `risk_evaluator_node`
- `watchdog_failsafe_node`
- `command_mux_node`
- `actuator_safety_limiter_node`
- `auto_controller_stub_node`
- `mission_mode_manager_node`
- `event_logger_node`

### Preview path

- `thruster_adapter_preview_node`

### Guarded thruster-test path

- `guarded_thruster_test_adapter_node`
- `thruster_test_safety_guardian_node`
- `thruster_test_hud_node`

### Guarded AUTO-takeover path

- `auto_takeover_manager_node`
- `auto_takeover_hud_node`

### Optional perception components

- `vision_quality_node`
- `false_positive_guard_node`
- `frame_freeze_detector_node`
- `multi_target_fusion_node`
- `waterline_horizon_node`

## Runtime Outputs

Generated session data is stored under:

~~~text
runtime_artifacts/<RUN_ID>/
~~~

Depending on the selected profile, a session can contain:

~~~text
terminal.log
ros_logs/
event_logs/
hardware_test_logs/
auto_takeover_logs/
web_video_server.log
~~~

The event logger can generate:

| File | Purpose |
|---|---|
| `time_series.csv` | Per-sample perception, risk, command, state, and metric data |
| `avoidance_cycles.csv` | Per-cycle timing and avoidance results |
| `metrics_summary.csv` | Aggregated metrics in CSV format |
| `metrics_summary.json` | Aggregated metrics in JSON format |
| `events.csv` | Human-readable event records |
| `events.jsonl` | JSON-lines event records |

Runtime outputs, ROS build products, caches, and local assistant directories are excluded from Git.

## Repository Structure

~~~text
.
├── README.md
├── PRD.md
├── AGENTS.md
├── SKILLS.md
├── docs/
│   ├── assets/
│   ├── CLEANUP_NOTES.md
│   ├── REPO_MAP.md
│   ├── RUNBOOK_POOL_EXISTING_CONTROL_PATH.md
│   └── THRUSTER_ARBITRATION_INTERFACE_REQUIREMENTS.md
└── seano_ca_ws/
    ├── README.md
    ├── run_pool_existing_control_path.sh
    ├── run_pool_thruster_hardware_test.sh
    ├── run_pool_auto_takeover_test.sh
    ├── scripts/
    └── src/
        └── seano_vision/
            ├── config/
            ├── launch/
            ├── models/
            ├── seano_vision/
            └── test/
~~~

## Build and Verification

Build the workspace:

~~~bash
cd seano_ca_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
~~~

Check Python syntax:

~~~bash
python3 -m compileall -q src/seano_vision/seano_vision
~~~

Check entry-point scripts:

~~~bash
bash -n run_pool_existing_control_path.sh
bash -n run_pool_thruster_hardware_test.sh
bash -n run_pool_auto_takeover_test.sh
~~~

Run tests:

~~~bash
colcon test --packages-select seano_vision
colcon test-result --verbose
~~~

All non-hardware checks must pass before a field test.

## Credential Handling

MQTT credentials must not be committed to this repository.

The guarded scripts load credentials from either:

- an absolute YAML file outside the repository; or
- explicit process-environment variables.

The secure credential loader rejects credential files located inside the repository, rejects symlinks, requires TLS, rejects insecure TLS configuration, and avoids printing secret values in logs.

## Documentation

| File | Purpose |
|---|---|
| `PRD.md` | Product requirements and system goals |
| `AGENTS.md` | Repository development guidance |
| `SKILLS.md` | Repository-specific verification procedures |
| `docs/REPO_MAP.md` | Repository and node map |
| `docs/RUNBOOK_POOL_EXISTING_CONTROL_PATH.md` | Baseline pool-test runbook |
| `docs/CLEANUP_NOTES.md` | Generated-file and cleanup policy |
| `docs/THRUSTER_ARBITRATION_INTERFACE_REQUIREMENTS.md` | Required production arbitration contract |

## License

The ROS package metadata declares the MIT license. A repository-level `LICENSE` file has not yet been added.
