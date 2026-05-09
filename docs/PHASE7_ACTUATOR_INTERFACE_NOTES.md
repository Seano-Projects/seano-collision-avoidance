# Phase 7 Actuator Interface Notes

## Current Safety Position

Field evidence reports MAVROS printing:

```text
RC override not supported by this FCU!
```

For the CUAV / ArduPilot Phase 7 hardware launch, `/mavros/rc/override` must not be treated
as a confirmed physical actuator path by default. The Phase 7 bridge now fails closed unless
both of these parameters are explicitly set true after bench confirmation:

```text
actuator_interface_supported:=true
actuator_interface_confirmed:=true
```

The default remains:

```text
actuator_interface:=rc_override
actuator_interface_supported:=false
actuator_interface_confirmed:=false
```

In the default state, the bridge publishes RC override release frames only and blocks active
avoidance actuator output. This is an actuator safety gate only; it does not validate physical
avoidance.

## Candidate Supported MAVROS Path

The next candidate interface for this ArduPilot / CUAV setup is MAVROS manual control:

```text
topic: /mavros/manual_control/send
type:  mavros_msgs/msg/ManualControl
```

This topic maps to the MAVLink `MANUAL_CONTROL` path through the MAVROS manual control plugin.
It still requires controlled bench validation with the vehicle made safe before it can be used
for avoidance output.

The MAVROS actuator-control message exists as:

```text
topic family: /mavros/actuator_control/*
type:         mavros_msgs/msg/ActuatorControl
```

However, the local MAVROS ArduPilot plugin list deny-lists the actuator-control plugin, so it is
not the immediate candidate for this Phase 7 hardware path.
