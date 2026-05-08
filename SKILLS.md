# SKILLS.md

# Codex Workflows for Lake-Test Hardware Development

This file defines safe repeatable workflows for using Codex in this repository. These are local repository instructions, not an installable ChatGPT Skill package.

Always follow `AGENTS.md` before using these workflows.

## Skill 1 - Read Before Editing

Use before every Codex task.

Prompt:

```text
Read AGENTS.md, PRD.md, SKILLS.md, README.md if present, and the relevant files under seano_ca_ws/src/seano_vision.

Do not edit any file yet.

Summarize:
1. active ROS 2 package,
2. launch files available,
3. hardware-related nodes,
4. topic flow,
5. files that should not be refactored aggressively,
6. safety risks for lake testing.
```

Expected output:

```text
Architecture summary
Files inspected
Hardware risks
No edits performed
```

## Skill 2 - Audit Hardware Launch

Use when checking readiness for lake testing.

Prompt:

```text
Audit the hardware launch path only. Do not edit.

Inspect:
1. seano_ca_ws/src/seano_vision/launch/phase7_cuav_usb_hardware.launch.py
2. seano_ca_ws/src/seano_vision/launch/demo_full_ca.launch.py
3. seano_ca_ws/src/seano_vision/launch/phase2_camera_usb_test.launch.py
4. corresponding Python nodes in seano_ca_ws/src/seano_vision/seano_vision

Report:
1. node name,
2. launch parameter,
3. whether it is declared in source,
4. topic publisher/subscriber contract,
5. safety impact,
6. minimal fix.
```

Do not request edits until the audit report is reviewed.

## Skill 3 - Low-Lag Field-Test Audit

Use when the program feels heavy or laggy.

Prompt:

```text
Analyze runtime lag risk for lake testing. Do not edit.

Inspect launch files and nodes that process image topics.

Report:
1. nodes subscribing to image topics,
2. nodes publishing debug or annotated images,
3. FPS, resolution, model, and debug parameters,
4. which topics may consume high bandwidth,
5. lowest-lag run configuration,
6. staged debug workflow from camera-only to full hardware run.
```

Terminal checks:

```bash
htop
ros2 node list
ros2 topic list
ros2 topic hz /seano/camera/image_raw
ros2 topic hz /seano/camera/image_raw_reliable
ros2 topic hz /camera/detections
ros2 topic hz /ca/risk
ros2 topic bw /seano/camera/image_raw_reliable
```

If on Jetson and available:

```bash
sudo tegrastats
jtop
```

## Skill 4 - Lake-Test Preflight Checklist

Use before hardware deployment.

Prompt:

```text
Prepare a lake-test preflight checklist for the current repo state.

Do not edit.

Base it on:
1. camera readiness,
2. detector readiness,
3. risk output readiness,
4. MAVROS/CUAV connection,
5. manual override,
6. failsafe behavior,
7. logging plan,
8. abort criteria.
```

Expected output:

```text
Preflight checklist
Required commands
Expected pass condition
Abort condition
Evidence to save
```

## Skill 5 - Apply Minimal Hardware Fix

Use only after a confirmed issue exists.

Prompt:

```text
Apply only the confirmed minimal hardware-related fix.

Do not refactor.
Do not change thresholds.
Do not change PWM values.
Do not change failsafe timing.
Do not rename launch files.
Do not commit.

After editing:
1. show exact diff,
2. explain every changed block,
3. state safety impact,
4. run static compile check if possible.
```

Static check:

```bash
python3 -m compileall -q seano_ca_ws/src/seano_vision/seano_vision seano_ca_ws/src/seano_vision/launch
```

## Skill 6 - Build and Source Workspace

Use when preparing to run ROS 2 commands.

From repo root:

```bash
cd seano_ca_ws
colcon build --symlink-install
source install/setup.bash
ros2 pkg executables seano_vision
```

If sourcing fails:

```bash
pwd
ls
ls install
find . -name setup.bash
```

Do not source a setup file from an older repository path.

## Skill 7 - Camera-Only Test

Use to isolate camera issues.

Commands:

```bash
cd seano_ca_ws
source install/setup.bash
ros2 launch seano_vision phase2_camera_usb_test.launch.py
```

In another terminal:

```bash
source seano_ca_ws/install/setup.bash
ros2 topic list
ros2 topic hz /seano/camera/image_raw
ros2 topic hz /seano/camera/image_raw_reliable
```

Record:

```text
camera device
resolution
FPS
CPU load
latency symptoms
```

## Skill 8 - Detector-Only Test

Use to isolate model inference lag.

Prompt for Codex:

```text
Inspect detector launch and detector_node.py. Do not edit.

Identify:
1. detector input image topic,
2. model path,
3. image size,
4. confidence threshold,
5. FPS limit,
6. annotated image output,
7. parameters that can reduce lag.
```

Do not change model or threshold without documenting the reason.

## Skill 9 - MAVROS / CUAV Sanity Check

Use before water deployment.

Commands may include:

```bash
ros2 topic echo /mavros/state
ros2 topic list | grep mavros
```

Codex must not modify MAVROS topic names, channel mapping, or RC override behavior without explicit instruction.

Expected report:

```text
MAVROS connected: yes/no
FCU mode observed:
RC override path present:
manual recovery path:
risk:
```

## Skill 10 - Field Evidence Report

Use after a lake test.

Prompt:

```text
Create a field evidence summary from provided logs, notes, screenshots, or rosbag-derived metrics.

Do not invent missing results.

Separate:
1. observed facts,
2. measured values,
3. interpretation,
4. limitations,
5. next test recommendation.
```

Required sections:

```text
Date/time:
Location:
Weather/water condition:
Hardware setup:
Launch command:
Topics monitored:
Observed behavior:
Issues:
Abort events:
Evidence files:
Conclusion:
Limitations:
Next action:
```

## Skill 11 - Git Safety

Before Codex edits:

```bash
git status
git checkout -b codex/<short-task-name>
```

After Codex edits:

```bash
git diff
git status
```

Only commit reviewed files.

Avoid committing:

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

Use targeted add:

```bash
git add AGENTS.md PRD.md SKILLS.md
```

Avoid:

```bash
git add .
```

unless the working tree is intentionally clean.

## Skill 12 - Required Report Format

Codex must report all tasks using:

```text
Objective:
Files inspected:
Files changed:
Why this matters for lake testing:
Safety impact:
Verification performed:
Verification not performed:
Remaining risks:
Next recommended action:
```
