# SEANO Collision Avoidance ROS 2 Workspace

This directory contains the active ROS 2 Humble workspace for the SEANO collision-avoidance system.

For complete architecture, safety, deployment, development, and field-test documentation, read:

```text
../README.md
```

## Primary Runtime

The current operator entry point is:

```bash
./run_ca.sh
```

Normal startup after the external SEANO system is ready:

```bash
cd ~/resource_git/seano-collision-avoidance2/seano_ca_ws
./run_ca.sh
```

Enter:

```text
YES
```

when the safety checklist has been physically verified.

The launcher handles the ROS environment, `ROS_DOMAIN_ID=0`, workspace setup, MQTT configuration, guarded preflight, professional console, and AUTO-takeover runtime.

## Launcher Commands

```bash
./run_ca.sh
./run_ca.sh --dry-check
./run_ca.sh --preflight-only
./run_ca.sh --rebuild
./run_ca.sh --verbose
```

## Runtime Policy

Startup is non-blocking with respect to FCU control state.

The CA perception and monitoring pipeline can remain active while the operator is in MANUAL or while the vehicle is DISARMED.

Collision-avoidance control becomes eligible only after:

```text
AUTO + ARMED + SOFTWARE_READY
```

Operator MANUAL/DISARM intervention is recoverable and does not require restarting the CA process.

## Underlying Runtime

`run_ca.sh` uses:

```text
run_pool_auto_takeover_test.sh
```

as the guarded lower-level runtime.

The other runners are retained for diagnostics:

```text
run_pool_existing_control_path.sh
run_pool_thruster_hardware_test.sh
```

Do not run multiple collision-avoidance profiles at the same time.

## Safety Boundary

This workspace reuses:

```text
external MAVROS
external /usv/thruster
external startup services
external MQTT infrastructure
```

Do not start a second MAVROS instance.

Do not create another publisher on:

```text
/mavros/rc/override
```

`/usv/thruster` must remain the external RC-override owner.

## Build and Verification

```bash
source /opt/ros/humble/setup.bash

colcon build --symlink-install --packages-select seano_vision
source install/setup.bash

python3 -m compileall -q src/seano_vision/seano_vision
python3 -m pytest src/seano_vision/test -q

./run_ca.sh --dry-check
```

Current verified baseline before the latest operational commit:

```text
308 passed
```

## HUD

Primary AUTO-takeover HUD:

```text
/ca/auto_takeover/debug_image
```

Browser:

```text
http://<JETSON_IP>:8080/stream?topic=/ca/auto_takeover/debug_image
```

## Stop

Use:

```text
Ctrl+C
```

in the terminal that started `run_ca.sh`.

See the repository root `README.md` before modifying safety-critical code.
