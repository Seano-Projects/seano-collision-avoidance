# PRD.md

# Product Requirements Document
## SEANO Lake-Test Hardware Collision Avoidance System

## 1. Purpose

This project prepares and validates a ROS 2 Humble vision-based collision avoidance stack for SEANO USV hardware testing on a lake. The system must support safe camera-based obstacle perception, collision-risk evaluation, mission-aware behavior, MAVROS/CUAV integration, and field-test evidence collection.

The priority is not feature quantity. The priority is stable hardware operation, traceable field evidence, low-lag runtime, and conservative safety behavior.

## 2. Target Use Case

Primary use case:

```text
Run the SEANO USV on a lake with camera-based perception and collision-avoidance supervision while preserving operator control, failsafe behavior, and field-test evidence.
```

Expected operating context:

```text
Vehicle: SEANO USV
Environment: lake / outdoor field-test area
Middleware: ROS 2 Humble
Main workspace: seano_ca_ws
Main package: seano_vision
Runtime computer: Jetson-class onboard computer or Linux field laptop
Autopilot / bridge: CUAV / ArduPilot / MAVROS path where enabled
Sensor emphasis: USB or onboard camera
Control emphasis: safe command path, manual recovery, failsafe observability
```

## 3. Problem Statement

A USV operating in a lake-test environment must detect visual hazards, estimate collision risk, and support avoidance behavior without creating unsafe actuation or misleading validation claims. The system must be stable enough for real hardware testing and lightweight enough to run without severe lag.

The central engineering problem is the integration of vision perception, risk evaluation, watchdog/failsafe logic, mission behavior, and hardware bridge operation under field constraints.

## 4. Product Goals

The system shall:

1. Acquire camera input reliably during outdoor testing.
2. Run obstacle detection at a usable FPS.
3. Publish interpretable collision-risk output.
4. Support mission-aware behavior and failsafe override.
5. Preserve a clear safety boundary before any hardware command output.
6. Support MAVROS/CUAV integration where configured.
7. Keep field-test runtime low-lag and observable.
8. Record enough evidence for thesis evaluation.
9. Provide staged launch workflows for camera-only, detector-only, CA debug, and hardware run.
10. Maintain operator recovery and safe stop procedures.

## 5. Non-Goals

The system shall not claim:

1. Certified maritime autonomy.
2. Safety certification.
3. Full COLREGs compliance.
4. Final field validation without controlled lake-test evidence.
5. Production readiness.
6. Guaranteed obstacle avoidance in all environmental conditions.
7. Performance improvement without measured data.

## 6. Stakeholders

Primary stakeholders:

1. Thesis author / operator.
2. Field-test supervisor.
3. Safety observer.
4. Thesis examiner.
5. Future developer maintaining the codebase.

## 7. Functional Requirements

### R1. Camera Acquisition

The system shall acquire and publish camera frames during hardware testing.

Acceptance criteria:

- Camera topic is clear and documented.
- FPS and resolution can be adjusted.
- Camera-only launch can run independently.
- Camera failure is diagnosable from ROS 2 topics.
- Camera stream does not overload the onboard computer.

### R2. Detection Pipeline

The system shall process camera input and publish detection output.

Acceptance criteria:

- Detector subscribes to the intended camera topic.
- Detector does not consume debug image topics unless intentionally configured.
- Model path, confidence threshold, image size, and inference device are explicit.
- Detection output can be monitored during field testing.

### R3. Risk Evaluation

The system shall convert detections and image context into collision-risk state.

Acceptance criteria:

- Risk output topic is observable.
- Debug image output can be disabled or reduced for low-lag field operation.
- Risk thresholds are not changed without justification.
- Risk output does not bypass safety supervision.

### R4. Watchdog and Failsafe

The system shall detect stale or unsafe runtime conditions.

Acceptance criteria:

- Camera/image freshness can be supervised.
- Risk or command freshness can be supervised where implemented.
- Failsafe state is observable.
- Failsafe behavior is conservative.
- Failsafe does not silently fail open.

### R5. Mission Mode Management

The system shall expose mission or avoidance state relevant to field testing.

Acceptance criteria:

- Mission state is observable.
- Failsafe can override normal behavior.
- Mode changes are explainable.
- Mission behavior is not modified casually during hardware testing.

### R6. Hardware Command Path

Where hardware output is enabled, the system shall preserve an explicit and safe command path.

Acceptance criteria:

- MAVROS / CUAV / RC override behavior is explicit.
- Operator override or recovery remains possible.
- RC override is not enabled accidentally.
- Thruster command mapping is not changed without verification.
- Stop script or safe shutdown path is available.

### R7. Logging and Evidence

The system shall collect enough evidence without causing runtime overload.

Recommended evidence:

```text
ros2 topic list
ros2 node list
camera FPS
detector FPS
risk topic output
MAVROS state
mission/failsafe state
selected launch command
parameter snapshot
screen recording or field video
operator notes
weather and lake condition notes
```

Acceptance criteria:

- Evidence is timestamped.
- Raw evidence is preserved.
- Field notes separate observed fact from interpretation.
- Image logging is controlled to avoid excessive lag.

### R8. Low-Lag Field Operation

The system shall support a low-lag hardware run mode.

Acceptance criteria:

- Debug images can be disabled or limited.
- Annotated image publication can be disabled or limited.
- Raw image recording is not enabled by default.
- Detector FPS is bounded.
- Full CA is not used when camera-only or detector-only debugging is sufficient.

## 8. Performance Risks

Expected bottlenecks:

1. Detector inference.
2. High camera resolution.
3. High image FPS.
4. Debug image publication.
5. Annotated image publication.
6. ROS bag recording of raw image topics.
7. Remote VS Code SSH rendering overhead.
8. Multiple image viewers.
9. Excessive logging.
10. Full pipeline debugging when only one subsystem needs testing.

## 9. Lake-Test Operating Modes

Recommended staged modes:

```text
Mode 1: camera-only bench
Mode 2: detector-only bench
Mode 3: risk-only / CA dry run
Mode 4: MAVROS/CUAV connection check
Mode 5: tethered or constrained lake test
Mode 6: low-speed supervised lake run
Mode 7: full evidence run
```

Do not jump directly to a full autonomous lake run.

## 10. Pre-Run Checklist

Before lake testing:

1. Confirm battery level.
2. Confirm manual control.
3. Confirm safe stop procedure.
4. Confirm network/SSH connection.
5. Confirm ROS 2 workspace builds.
6. Confirm camera stream.
7. Confirm detector output.
8. Confirm risk output.
9. Confirm MAVROS state if used.
10. Confirm failsafe/stop behavior.
11. Confirm field-test area is clear.
12. Confirm observer/operator roles.
13. Confirm logging plan.
14. Confirm weather and water condition are acceptable.

## 11. Abort Criteria

Abort the run if:

1. Manual control is lost.
2. RC override cannot be released.
3. MAVROS connection is unstable.
4. Camera stream freezes.
5. Detector FPS collapses.
6. CPU/GPU load causes severe lag.
7. Failsafe state is unclear.
8. Boat behavior differs from expected command.
9. Weather or water condition becomes unsafe.
10. Operator cannot clearly observe the vessel.

## 12. Evidence Boundary

Allowed claim after bench/hardware integration:

```text
The stack was integrated and exercised on the hardware path under supervised test conditions.
```

Allowed claim after controlled lake test with evidence:

```text
The system demonstrated the observed behavior under the tested lake conditions and recorded scenario constraints.
```

Disallowed claim without stronger evidence:

```text
The system is fully validated for real-world autonomous collision avoidance.
```

## 13. Immediate Engineering Priorities

1. Clean repo and avoid committing runtime artifacts.
2. Ensure hardware launch parameters match source node declarations.
3. Ensure detector input uses camera stream, not debug image output.
4. Ensure watchdog/failsafe supervision is not bypassed.
5. Build a low-lag field-test workflow.
6. Measure FPS and CPU/GPU load before optimizing.
7. Keep test evidence organized and timestamped.
