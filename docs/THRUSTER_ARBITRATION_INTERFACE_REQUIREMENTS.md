# Thruster Arbitration Interface Requirements

## Scope and current hazard

The current external `seano/USV-001/thruster` MQTT path is last-message-wins,
keeps replaying the last command, and has no auditable ownership, priority,
lease, acknowledgement, or command timeout. A web/cloud publisher can therefore
race collision avoidance. The collision-avoidance repository must remain preview
only until the external system implements and validates this contract.

## Required arbitration contract

Every command envelope must contain an authenticated `source_id`, controller
`priority`, monotonically increasing `sequence`, sender `timestamp`, and a short
`lease_timeout_ms`. Retained command messages must be rejected. Clock tolerance,
duplicate handling, sequence reset, and reconnect behavior must be specified.

Control requires explicit acquire and release:

1. Collision avoidance sends `ACQUIRE` with source, requested priority, lease,
   sequence, timestamp, and current FCU state preconditions.
2. The arbiter grants a unique lease/owner token and acknowledges the effective
   owner, priority, expiry, and FCU/mode state. No motion command is valid before
   this acknowledgement.
3. Commands refresh the lease and include the token. Expired, stale, retained,
   out-of-order, unowned, or state-incompatible commands are rejected and
   acknowledged with a reason.
4. `HOLD_COURSE` sends explicit `RELEASE`; the arbiter acknowledges release and
   returns control through the defined mode-handover procedure. Release is not a
   zero-throttle ownership claim.

Recommended logical payload:

```json
{"type":"COMMAND","source_id":"collision_avoidance","priority":60,
 "lease_id":"opaque","sequence":42,"timestamp_ms":0,"lease_timeout_ms":300,
 "throttle":16.5,"steering":0.0,"requested_mode":"MANUAL"}
```

Use separate request/status topics (for example `thruster/arbitration/request`
and `thruster/arbitration/status`). Status must report request sequence,
accepted/rejected, reason, current owner and priority, lease expiry, effective
throttle/steering, hardware-output state, FCU connected/armed/mode state, manual
override state, watchdog state, and last-applied timestamp.

## Priority, gates, and fail-safe behavior

Manual/operator authority always outranks autonomy. Emergency stop has the
highest priority, followed by manual control, collision avoidance, and normal
mission control. Exact priority values are owned by the external arbiter.

Acquisition is allowed only when the FCU connection, arm state, operating mode,
actuator interface, and command conversion have all been confirmed. Mode change
must be a two-phase handover: readiness acknowledgement first, requested FCU mode
second, and motion command only after both are acknowledged. A mode failure must
not leave a lease claiming active control.

The arbiter watchdog must neutralize/release on lease expiry, stale timestamp,
missing heartbeat, invalid range, sequence regression, owner mismatch, FCU state
change, manual takeover, or communication loss. Fail-safe transitions and the
actual applied output must be acknowledged and logged. Collision avoidance must
never infer hardware application from publishing a request.

Until this contract is implemented end-to-end, `/ca/actuator_path_ready` remains
false, the repository emits preview telemetry only, and it must neither request
MANUAL nor publish MQTT/MAVROS actuator commands.
