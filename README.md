# seano-collision-avoidance

Vision-based collision avoidance stack for the SEANO Unmanned Surface Vehicle (USV).

This repository contains the ROS 2 workspace used for obstacle perception, risk evaluation, avoidance decision logic, runtime monitoring, and structured field-test logging. The system is designed to support safe USV operation by detecting visual obstacles, estimating collision risk, and producing internal avoidance commands that can be reviewed, logged, and integrated with the vehicle control stack.

## Current Operating Mode

The recommended field-test configuration uses the existing SEANO vehicle control path for physical actuation.

In this mode:

- the collision avoidance stack runs camera perception, detection, risk scoring, internal command generation, and logging;
- the existing SEANO control stack remains responsible for physical actuation;
- `/usv/thruster` remains the only publisher to `/mavros/rc/override`;
- `mavros_rc_override_bridge_node` from this repository is intentionally disabled;
- no new MAVROS instance is launched by this repository.

This configuration avoids duplicate RC override publishers while still producing complete perception, risk, command, and event logs for analysis.

## Features

- Camera-based obstacle detection using YOLOv8.
- Risk evaluation based on proximity, centrality, approach, bearing consistency, and visual time-to-collision indicators.
- Risk-class and command generation for hold-course, slow-down, turn, and stop decisions.
- Watchdog and perception-loss fail-safe handling.
- Structured runtime logging for time-series data, avoidance cycles, events, and summary metrics.
- Field-test run script for existing-control-path operation.
- Optional full-profile perception nodes for extended experiments and future integration.

## Platform

Target platform:

- NVIDIA Jetson Orin
- ROS 2 Humble
- Python-based ROS 2 nodes
- YOLOv8 perception model
- MAVROS-compatible vehicle environment
- SEANO existing vehicle control stack

## Quick Start

Use the existing-control-path field-test script:

```bash
cd seano_ca_ws
./run_pool_existing_control_path.sh
```

Stop the run with `Ctrl+C` in the same terminal that started the script. This stops the collision avoidance launch process started by this repository. It does not stop the existing SEANO control services.

Do not use `run_phase7_monitor_no_log.sh` for the current existing-control-path field-test workflow. That script belongs to an older operational path and does not represent the current recommended logging and no-bridge configuration.

## Field-Test Preflight

Before running a field test, verify:

- MAVROS is connected.
- Vehicle mode is not RTL unless the operator explicitly intends that state.
- `/usv/thruster` is the only publisher to `/mavros/rc/override`.
- No `mavros_rc_override_bridge_node` from this repository is already running.
- Camera and detector are physically ready.
- Operator/manual authority is available.
- Test area is clear and safe.
- The vehicle control operator understands that physical actuation remains under the existing SEANO control stack.

The run script performs conservative preflight checks before launching the collision avoidance stack.

## Runtime Outputs

The event logger writes structured files under the configured event log directory.

Important outputs include:

| File | Purpose |
|---|---|
| `time_series.csv` | Per-sample perception, risk, command, status, and metric data. |
| `avoidance_cycles.csv` | Per-cycle timing, response, and avoidance summary data. |
| `metrics_summary.csv` | Aggregated metric summary in CSV format. |
| `metrics_summary.json` | Aggregated metric summary in JSON format. |
| `events.csv` | Human-readable event log. |
| `events.jsonl` | JSON lines event log for programmatic analysis. |

Frame capture is disabled by default for the current workflow.

## Repository Structure

```text
.
├── AGENTS.md
├── PRD.md
├── SKILLS.md
├── README.md
├── docs/
│   ├── CLEANUP_NOTES.md
│   ├── REPO_MAP.md
│   └── RUNBOOK_POOL_EXISTING_CONTROL_PATH.md
└── seano_ca_ws/
    ├── run_pool_existing_control_path.sh
    ├── scripts/
    └── src/
        └── seano_vision/
            ├── launch/
            ├── config/
            ├── models/
            └── seano_vision/
```

## Main Runtime Nodes

The current existing-control-path workflow uses the core collision avoidance pipeline:

- `camera_node.py`
- `detector_node.py`
- `risk_evaluator_node.py`
- `watchdog_failsafe_node.py`
- `command_mux_node.py`
- `actuator_safety_limiter_node.py`
- `auto_controller_stub_node.py`
- `mission_mode_manager_node.py`
- `event_logger_node.py`

Optional full-profile perception nodes are retained for extended configurations and should not be removed:

- `vision_quality_node.py`
- `false_positive_guard_node.py`
- `frame_freeze_detector_node.py`
- `multi_target_fusion_node.py`
- `waterline_horizon_node.py`

## Documentation

| File | Description |
|---|---|
| `PRD.md` | Product requirements and system goals. |
| `AGENTS.md` | Operational guidance for AI-assisted development in this repository. |
| `SKILLS.md` | Repository-specific development and verification skills. |
| `docs/REPO_MAP.md` | Detailed repository map and node classification. |
| `docs/RUNBOOK_POOL_EXISTING_CONTROL_PATH.md` | Field-test runbook for the existing-control-path workflow. |
| `docs/CLEANUP_NOTES.md` | Cleanup policy and generated-file handling notes. |

## Safety Notes

This repository is used around a real vehicle platform. Treat launch files, actuator interfaces, fail-safe logic, and RC override paths as safety-critical.

Key rules:

- Do not run multiple publishers to `/mavros/rc/override`.
- Do not enable the direct RC override bridge unless the actuation interface has been explicitly validated.
- Keep operator/manual authority available during field testing.
- Prefer the existing-control-path script for current field tests.
- Review logs after each run before making further changes.

## Development Checks

Common non-hardware checks:

```bash
cd seano_ca_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
```

Python syntax check:

```bash
python3 -m compileall -q seano_ca_ws/src/seano_vision/seano_vision
```

Script syntax check:

```bash
bash -n seano_ca_ws/run_pool_existing_control_path.sh
```

## License

This repository does not currently include a license file. Until a license is added, no reuse, redistribution, or modification rights are granted beyond what the repository owner explicitly permits.
