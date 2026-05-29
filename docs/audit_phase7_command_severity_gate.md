# Phase 7 Command Severity Gate Audit

## Root Cause

The HUD evidence showed that symbolic collision-avoidance commands could exceed
the operator risk band:

- LOW risk sometimes displayed a held `TURN_RIGHT`.
- MEDIUM risk could display full `TURN_RIGHT` or `STOP`.
- Watchdog command dwell could preserve a previous full avoidance command after
  risk dropped, without a clear HUD/log label showing that the command was held.

The root cause was that risk scoring and command selection were coupled by
thresholds, encounter labels, vTTC urgency, and command hold/dwell logic, but
there was no single final policy gate enforcing the operator-facing LOW,
MEDIUM, and HIGH command bands before publishing raw or safe commands.

## Changed Files

- `seano_ca_ws/src/seano_vision/seano_vision/risk_policy.py`
- `seano_ca_ws/src/seano_vision/seano_vision/risk_evaluator_node.py`
- `seano_ca_ws/src/seano_vision/seano_vision/watchdog_failsafe_node.py`
- `seano_ca_ws/scripts/check_phase7_sync_log.py`
- `docs/audit_phase7_command_severity_gate.md`

No MAVROS topics, RC override topics, PWM values, RC channel mapping, manual
authority gates, launch defaults, or runner configuration were changed.

## Risk Band Policy

| Risk band | Risk range | Allowed normal commands |
| --- | --- | --- |
| LOW | `risk < 0.30` | `HOLD_COURSE` |
| MEDIUM | `0.30 <= risk < 0.60` | `SLOW_DOWN`, `TURN_LEFT_SLOW`, `TURN_RIGHT_SLOW` |
| HIGH | `risk >= 0.60` | `STOP`, `TURN_LEFT`, `TURN_RIGHT` |

LOW may temporarily show an old avoidance command only when explicitly labeled
with `command_latched=true` or `command_source=LATCHED` / `RECOVERY`.

## Exceptions

The policy gate permits explicit exception sources:

- `FAILSAFE`
- `INVALID_DATA`
- `EMERGENCY`
- `EMERGENCY_VTTC`

These sources may command `STOP` outside the normal risk band, but the HUD/log
must expose the source so the event is not interpreted as a normal LOW or MEDIUM
risk decision.

## Verification Procedure

Static checks allowed in WSL:

```bash
python3 -m compileall -q seano_ca_ws/src/seano_vision/seano_vision seano_ca_ws/src/seano_vision/launch
cd seano_ca_ws && colcon build --symlink-install
git diff --check
```

Offline terminal log check:

```bash
python3 seano_ca_ws/scripts/check_phase7_sync_log.py terminal_log.txt
```

The checker scans `phase7_sync` lines and flags:

- LOW selected avoidance commands without latch or exception labels.
- MEDIUM selected full `STOP` / `TURN_LEFT` / `TURN_RIGHT` without failsafe or
  emergency source.
- HIGH selected `HOLD_COURSE` while CA active or takeover is true, unless manual
  authority or release state is present.
- Any line with `command_policy_valid=false`.

No hardware launch, camera, MAVROS, MAVProxy, FCU, or Jetson-dependent command
is required for this verification.
