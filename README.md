# SEANO Collision Avoidance

ROS 2-based collision avoidance system for the SEANO Unmanned Surface Vehicle (USV).

The system combines camera-based object detection, visual collision-risk evaluation, guarded avoidance control, AUTO takeover, operator override handling, browser monitoring, and runtime logging on NVIDIA Jetson.

## Run

The active runtime is started from the Jetson with:

```bash
cd ~/resource_git/seano-collision-avoidance2/seano_ca_ws
./run_ca.sh
```

The launcher prepares the ROS environment, validates the SEANO interfaces, loads the current MQTT configuration, performs the required safety checks, and starts the complete collision avoidance runtime.

When prompted:

```text
Ketik YES untuk menjalankan CA:
```

enter:

```text
YES
```

To stop the runtime:

```text
Ctrl+C
```

For normal operation, `run_ca.sh` is the only entry point that needs to be used.

---

## System Flow

```text
Camera
  |
  v
YOLOv8n TensorRT
  |
  v
Object Detection
  |
  v
Risk Evaluation
  |
  v
Collision Avoidance Decision
  |
  v
Safety / Watchdog
  |
  v
AUTO Takeover Manager
  |
  v
SEANO Control System
```

The detector provides object position and bounding-box information to the risk evaluator.

The risk evaluator derives visual collision indicators including:

- proximity;
- centrality;
- approach;
- bearing consistency;
- visual time-to-collision (`vTTC`).

The resulting risk value is converted into one of the supported commands:

```text
HOLD_COURSE
SLOW_DOWN
TURN_LEFT_SLOW
TURN_RIGHT_SLOW
TURN_LEFT
TURN_RIGHT
STOP
```

A generated command does not automatically produce vehicle movement. The command must still pass the control and safety gates before it can be applied.

---

## Control Behaviour

The CA process can be started without requiring a specific FCU control state.

It may be started while the vehicle is:

```text
MANUAL + DISARMED
MANUAL + ARMED
AUTO + DISARMED
AUTO + ARMED
```

The perception, risk evaluation, HUD, and runtime monitoring remain active independently from vehicle control authority.

Collision avoidance becomes eligible only when:

```text
AUTO + ARMED + SOFTWARE_READY
```

The runtime then enters:

```text
AUTO_MISSION_MONITORING
```

When a valid hazard requires intervention, the system requests the guarded takeover path:

```text
AUTO
  |
  v
AUTO_MISSION_MONITORING
  |
  v
Hazard confirmed
  |
  v
MANUAL takeover
  |
  v
Collision avoidance
  |
  v
Hazard clear
  |
  v
Release control
  |
  v
Return to AUTO
```

The system does not automatically arm or disarm the vehicle.

---

## Operator Authority

Operator authority always has priority.

If the operator changes from AUTO to MANUAL or disarms the FCU, collision avoidance control is released without shutting down the CA process.

The runtime remains active and can recover when the operator later returns the vehicle to:

```text
AUTO + ARMED
```

provided the software and safety conditions are healthy.

Typical behaviour:

```text
AUTO + ARMED
     |
     v
Operator selects MANUAL
     |
     v
OPERATOR_OVERRIDE
     |
     v
Operator returns to AUTO
     |
     v
AUTO + ARMED + SOFTWARE_READY
     |
     v
AUTO_MISSION_MONITORING
```

This sequence can occur repeatedly during the same runtime session.

---

## Perception

Current detector configuration:

| Parameter | Value |
| --- | --- |
| Model | YOLOv8n |
| Inference backend | TensorRT |
| Precision | FP16 |
| Model input | 416 × 416 |
| Camera image | 640 × 480 |
| ROS 2 | Humble |
| Platform | NVIDIA Jetson |

Runtime TensorRT model:

```text
seano_ca_ws/src/seano_vision/models/yolov8n.engine
```

Source model:

```text
seano_ca_ws/src/seano_vision/models/yolov8n.pt
```

The TensorRT engine is generated for the target Jetson environment and should not be assumed portable to another GPU/CUDA/TensorRT installation.

---

## Risk Configuration

The active vehicle configuration is stored in:

```text
seano_ca_ws/src/seano_vision/config/alfin7_hardware_light.yaml
```

Current key parameters:

| Parameter | Value |
| --- | ---: |
| Camera HFOV | 67.5° |
| CENTER band ratio | 0.35 |
| Approx. CENTER bearing | ±11.8125° |
| Risk evaluator minimum detection score | 0.45 |
| Enter avoidance | 0.45 |
| Exit avoidance | 0.28 |
| Slow threshold | 0.35 |
| Turn slow threshold | 0.45 |
| Turn threshold | 0.60 |
| Stop threshold | 0.78 |
| Visual timeout | 1.20 s |

The CENTER band represents the region directly ahead of the vessel. Objects outside this band are treated relative to their port or starboard position when an avoidance direction is selected. :contentReference[oaicite:1]{index=1}

---

## Visual Freshness

The risk evaluator monitors both direct image reception and detector-derived visual evidence.

The following values are exposed in `/ca/metrics`:

```text
img_age_s
det_age_s
visual_age_s
visual_fresh_source
```

Effective visual freshness is determined from the freshest valid source:

```text
visual_age = min(img_age, det_age)
```

This prevents a delayed image callback from being interpreted as complete visual loss when the detector is still processing fresh frames.

If visual evidence is genuinely unavailable beyond the configured timeout, the system enters:

```text
LOST_PERCEPTION
```

and the safety path selects:

```text
STOP
```

---

## External SEANO Interface

The collision avoidance runtime reuses the control infrastructure already running on SEANO.

The current integration uses:

```text
external MAVROS
/usv/thruster
/mavros/set_mode
external MQTT configuration
ROS_DOMAIN_ID=0
```

`run_ca.sh` does not replace the main SEANO startup system. It sources ROS 2 Humble, sets `ROS_DOMAIN_ID=0`, validates the MQTT configuration, and then starts the guarded CA runtime. :contentReference[oaicite:2]{index=2}

The current MQTT configuration path is:

```text
/home/seano/Seano_ws/src/seano_startup/config/system.yaml
```

This path is specific to the current SEANO Jetson installation.

When deploying to another vehicle or Jetson, review this path together with the camera, TensorRT model, vehicle geometry, and control mapping.

Credentials must not be committed to this repository.

---

## HUD

AUTO takeover HUD topic:

```text
/ca/auto_takeover/debug_image
```

Browser:

```text
http://<JETSON_IP>:8080/stream?topic=/ca/auto_takeover/debug_image
```

The HUD provides the current detection result, risk, selected command, FCU state, takeover status, control gate, blocked reason, and abort reason.

Useful runtime topics:

```text
/ca/auto_takeover/status_json
/ca/metrics
/ca/watchdog_status
/camera/detections
/seano/camera/image_raw_reliable
```

Examples:

```bash
ros2 topic echo /ca/auto_takeover/status_json --once
```

```bash
ros2 topic echo /ca/metrics
```

```bash
ros2 topic echo /ca/watchdog_status
```

---

## Runtime Logs

Each run creates a session under:

```text
runtime_artifacts/
```

The session contains runtime evidence such as:

```text
terminal output
ROS logs
AUTO takeover events
control evidence
HUD/web-video logs
```

The default console hides repetitive ROS telemetry and keeps important runtime events visible.

For full console output:

```bash
./run_ca.sh --verbose
```

---

## Project Structure

The main files for the current runtime are:

```text
seano_ca_ws/
├── run_ca.sh
├── scripts/
│   └── ca_pretty_console.py
└── src/seano_vision/
    ├── config/
    │   └── alfin7_hardware_light.yaml
    ├── launch/
    │   └── auto_takeover_test.launch.py
    ├── models/
    │   └── yolov8n.pt
    ├── seano_vision/
    │   ├── detector_node.py
    │   ├── risk_evaluator_node.py
    │   ├── watchdog_failsafe_node.py
    │   ├── auto_takeover_manager_node.py
    │   └── auto_takeover_state.py
    └── test/
```

`auto_takeover_state.py` contains the guarded state machine used for FCU state, operator override, takeover, release, and recovery handling. The hazard command set currently includes `SLOW_DOWN`, slow/full left and right turns, and `STOP`. :contentReference[oaicite:3]{index=3}

---

## Development

After modifying source code:

```bash
cd ~/resource_git/seano-collision-avoidance2/seano_ca_ws
./run_ca.sh --rebuild
```

Run the complete test suite before field testing:

```bash
source /opt/ros/humble/setup.bash
python3 -m pytest src/seano_vision/test -q
```

Current verified baseline:

```text
308 passed
```

Static runtime validation:

```bash
./run_ca.sh --dry-check
```

Read-only validation against the connected SEANO system:

```bash
./run_ca.sh --preflight-only
```

Both commands use the same active launcher and do not represent separate operational runtimes. The available launcher options are defined directly in `run_ca.sh`. :contentReference[oaicite:4]{index=4}

---

## Field Testing

Before using AUTO operation, verify that the vehicle itself is ready for navigation.

Check at minimum:

```text
battery condition
FCU connection
GPS / navigation solution
EKF state
arming status
operator MANUAL authority
emergency stop availability
```

The collision avoidance system does not bypass autopilot-level safety or pre-arm checks.

During development and field testing, keep direct operator control available at all times.
