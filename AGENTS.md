# AGENTS.md

# SEANO Collision Avoidance 2 - Codex Agent Instructions

This repository is a ROS 2 Humble hardware-testing codebase for SEANO USV lake trials. Treat all changes as safety-critical because the software may affect a real unmanned surface vehicle operating in open water.

Codex must behave like a conservative engineering assistant. The goal is not to rewrite the system. The goal is to make small, reviewable, testable improvements that preserve operator safety, field-test traceability, and hardware reliability.

## Project Context

Primary workspace:

```text
seano_ca_ws/
```

Primary ROS 2 package:

```text
seano_ca_ws/src/seano_vision/
```

Important source folders:

```text
seano_ca_ws/src/seano_vision/seano_vision/
seano_ca_ws/src/seano_vision/launch/
seano_ca_ws/src/seano_vision/config/
seano_ca_ws/src/seano_vision/models/
```

Visible hardware-oriented files include:

```text
seano_ca_ws/src/seano_vision/launch/phase7_cuav_usb_hardware.launch.py
seano_ca_ws/src/seano_vision/launch/demo_full_ca.launch.py
seano_ca_ws/src/seano_vision/launch/phase2_camera_usb_test.launch.py
seano_ca_ws/src/seano_vision/seano_vision/camera_node.py
seano_ca_ws/src/seano_vision/seano_vision/detector_node.py
seano_ca_ws/src/seano_vision/seano_vision/risk_evaluator_node.py
seano_ca_ws/src/seano_vision/seano_vision/watchdog_failsafe_node.py
seano_ca_ws/src/seano_vision/seano_vision/mission_mode_manager_node.py
seano_ca_ws/src/seano_vision/seano_vision/mavros_rc_override_bridge_node.py
seano_ca_ws/src/seano_vision/stop_phase7_safe.sh
```

## Hardware Trial Mindset

This repository is being prepared for lake testing. Codex must assume that poor changes can create unsafe boat behavior, loss of field evidence, bad actuator commands, unstable MAVROS integration, or misleading thesis claims.

Before any edit, Codex must identify whether the task affects:

1. Camera acquisition.
2. Object detection.
3. Collision-risk evaluation.
4. Watchdog or failsafe logic.
5. Mission mode management.
6. MAVROS / CUAV / RC override behavior.
7. Thruster command mapping.
8. Field-test logging or evidence.
9. Launch files used for hardware runs.

If any item above is affected, keep the patch minimal.

## Expected Hardware Runtime Flow

The expected field-test flow is:

```text
USB / onboard camera
-> camera_node
-> detector_node
-> risk_evaluator_node
-> watchdog_failsafe_node
-> mission_mode_manager_node
-> command / takeover / RC override path
-> MAVROS / CUAV / ArduPilot
-> SEANO USV differential thrusters
```

The operator must retain a safe manual or abort path. Software must not silently bypass watchdog, failsafe, or mission-state supervision.

## Operating Rules for Codex

Before editing:

1. Read this file.
2. Inspect the exact launch file involved.
3. Inspect the exact Python node involved.
4. Compare launch parameters against `declare_parameter(...)`.
5. Trace relevant topic publishers and subscribers.
6. State the expected runtime effect.
7. Only then apply a small patch if requested.

Codex must not edit files just because they look untidy.

## Files Requiring Special Care

Do not broadly refactor these files:

```text
seano_ca_ws/src/seano_vision/seano_vision/camera_node.py
seano_ca_ws/src/seano_vision/seano_vision/detector_node.py
seano_ca_ws/src/seano_vision/seano_vision/risk_evaluator_node.py
seano_ca_ws/src/seano_vision/seano_vision/watchdog_failsafe_node.py
seano_ca_ws/src/seano_vision/seano_vision/mission_mode_manager_node.py
seano_ca_ws/src/seano_vision/seano_vision/mavros_rc_override_bridge_node.py
seano_ca_ws/src/seano_vision/launch/demo_full_ca.launch.py
seano_ca_ws/src/seano_vision/launch/phase7_cuav_usb_hardware.launch.py
seano_ca_ws/src/seano_vision/launch/phase2_camera_usb_test.launch.py
```

Do not rename launch files unless explicitly requested.

## Safety-Critical Restrictions

Do not change the following without explicit user instruction and engineering justification:

1. MAVROS topic names.
2. RC override topic names.
3. Thruster channel mapping.
4. PWM neutral, minimum, maximum, forward, reverse, or trim values.
5. Failsafe timeout values.
6. Watchdog timeout values.
7. Auto-enable behavior.
8. Manual override behavior.
9. Risk thresholds.
10. Mission-state transition timing.
11. Camera topic names used by the hardware launch.
12. Model path or detector confidence thresholds used during a field test.

Do not bypass safety layers for convenience.

## Lake Test Safety Rules

For field-test preparation, Codex must preserve these principles:

1. The boat must be recoverable by operator action.
2. Autonomous or assisted behavior must be explicitly enabled.
3. RC override must be explicitly enabled and releasable.
4. Failsafe state must be observable.
5. Camera, detector, risk, MAVROS, and mission-state health must be observable before launch.
6. Logging must not overload the onboard computer.
7. Raw field data must be preserved.
8. Thesis claims must match the available evidence.

## Performance Rules

Lake testing must prioritize stable runtime over heavy visualization.

During field testing, avoid enabling unnecessary:

```text
high-resolution debug image
annotated image stream
raw image rosbag recording
excessive console logging
multiple image viewers
unneeded helper nodes
```

If performance is poor, Codex must recommend staged profiling before optimizing:

```text
camera only
-> detector only
-> risk only
-> full CA
-> hardware / MAVROS path
```

## Required Verification

Static Python check:

```bash
python3 -m compileall -q seano_ca_ws/src/seano_vision/seano_vision seano_ca_ws/src/seano_vision/launch
```

ROS 2 build check:

```bash
cd seano_ca_ws
colcon build --symlink-install
source install/setup.bash
ros2 pkg executables seano_vision
```

Hardware-related checks when connected:

```bash
ros2 node list
ros2 topic list
ros2 topic hz /seano/camera/image_raw
ros2 topic hz /seano/camera/image_raw_reliable
ros2 topic hz /camera/detections
ros2 topic hz /ca/risk
ros2 topic echo /mavros/state
```

Do not claim any command passed unless it was actually run.

## Field-Test Evidence Discipline

Do not fabricate:

1. Lake-test success.
2. Obstacle-avoidance success.
3. Field runtime duration.
4. MAVROS stability.
5. Detection accuracy.
6. FPS.
7. CPU/GPU load.
8. Battery endurance.
9. Safety validation.

If evidence is unavailable, state that it is unavailable.

## Git Rules

Do not commit build or runtime artifacts:

```text
build/
install/
log/
logs/
__pycache__/
*.bag
*.db3
*.mcap
*.tlog
*.ulg
*.bin
*.raw
temporary waypoints
runtime outputs
```

Before edits:

```bash
git status
git checkout -b codex/<short-task-name>
```

After edits:

```bash
git diff
git status
```

Do not use `git add .` unless the working tree is intentionally clean.

## Report Format

After every task, Codex must report:

```text
Objective:
Files inspected:
Files changed:
Engineering rationale:
Safety impact:
Verification performed:
Verification not performed:
Remaining risks:
Next recommended action:
```
