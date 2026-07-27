# SEANO Collision Avoidance ROS 2 Workspace

This directory contains the active ROS 2 Humble workspace for SEANO collision-avoidance development and pool testing.

The previous workspace README described an older direct RC-override architecture. The current pool-test procedures reuse external MAVROS and `/usv/thruster`. They do not launch another MAVROS instance or `mavros_rc_override_bridge_node`.

See the repository root `README.md` for the complete architecture, safety boundary, and operating procedures.

## Entry Points

| Script | Current role |
|---|---|
| `run_pool_existing_control_path.sh` | Default safe preview baseline with no hardware output |
| `run_pool_thruster_hardware_test.sh` | Guarded MANUAL-mode thruster test |
| `run_pool_auto_takeover_test.sh` | Guarded AUTO-to-MANUAL takeover and AUTO restoration test |

These profiles are mutually exclusive.

## New Terminal Setup

~~~bash
cd ~/resource_git/seano-collision-avoidance2/seano_ca_ws

source /opt/ros/humble/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=0
~~~

## Safe Preview Baseline

~~~bash
./run_pool_existing_control_path.sh
~~~

Fixed safety profile:

~~~text
dry_run=true
hardware_output_enabled=false
mqtt_publish_enabled=false
use_mavros=false
use_rc_override_bridge=false
~~~

HUD topic:

~~~text
/ca/debug_image
~~~

## Guarded Thruster Test

Dry check:

~~~bash
./run_pool_thruster_hardware_test.sh --dry-check
~~~

Read-only preflight:

~~~bash
SEANO_MQTT_ENV_FILE=/absolute/path/to/system.yaml \
./run_pool_thruster_hardware_test.sh --preflight-only
~~~

A real run requires the environment confirmations and exact operator confirmation documented in the root README.

The operator performs MANUAL-mode selection and arming. This script does not call `set_mode` and does not arm or disarm the FCU.

HUD topic:

~~~text
/ca/hardware_test/debug_image
~~~

## Guarded AUTO Takeover

Dry check:

~~~bash
./run_pool_auto_takeover_test.sh --dry-check
~~~

Read-only preflight:

~~~bash
SEANO_MQTT_ENV_FILE=/absolute/path/to/system.yaml \
./run_pool_auto_takeover_test.sh --preflight-only
~~~

The test requires external MAVROS, `/mavros/set_mode`, and `/usv/thruster` as the sole RC override publisher.

HUD topic:

~~~text
/ca/auto_takeover/debug_image
~~~

## Build and Test

~~~bash
source /opt/ros/humble/setup.bash

colcon build --symlink-install

python3 -m compileall -q src/seano_vision/seano_vision

bash -n run_pool_existing_control_path.sh
bash -n run_pool_thruster_hardware_test.sh
bash -n run_pool_auto_takeover_test.sh

colcon test --packages-select seano_vision
colcon test-result --verbose
~~~

## Safety Rules

- Do not run more than one collision-avoidance profile at the same time.
- Do not start a second publisher on `/mavros/rc/override`.
- Keep `/usv/thruster` as the sole RC override publisher.
- Keep operator authority, tether, and emergency stop available.
- Keep MQTT credentials outside this repository.
- Stop the active profile with `Ctrl+C` in its starting terminal.
- Do not stop or modify external SEANO startup services from this workspace.
- Use the safe preview baseline unless a guarded physical-test procedure has been explicitly approved.
