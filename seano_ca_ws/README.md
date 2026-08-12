# SEANO Collision Avoidance Workspace

ROS 2 Humble workspace for the SEANO collision avoidance system.

## Run

```bash
cd ~/resource_git/seano-collision-avoidance2/seano_ca_ws
./run_ca.sh
```

Enter:

```text
YES
```

after verifying the safety checklist.

`run_ca.sh` is the active operator entry point. It prepares the ROS environment, validates the current SEANO interfaces, starts the collision avoidance runtime, and provides the operator console.

For complete runtime, architecture, monitoring, configuration, and development documentation, see:

```text
../README.md
```
