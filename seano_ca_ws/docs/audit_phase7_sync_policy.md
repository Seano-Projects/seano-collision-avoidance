# Phase 7 Risk/HUD/Override Synchronization Audit

Date: 2026-05-26

## Scope

Audited Phase 7 WSL workspace paths used by the formal runner:

- `run_phase7_monitor_no_log.sh`
- `phase7_mode_authority_bridge.py`
- `src/seano_vision/launch/phase7_cuav_usb_hardware.launch.py`
- `src/seano_vision/launch/demo_full_ca.launch.py`
- `src/seano_vision/seano_vision/risk_evaluator_node.py`
- `src/seano_vision/seano_vision/watchdog_failsafe_node.py`
- `src/seano_vision/seano_vision/auto_controller_stub_node.py`
- `src/seano_vision/seano_vision/command_mux_node.py`
- `src/seano_vision/seano_vision/actuator_safety_limiter_node.py`
- `src/seano_vision/seano_vision/mavros_rc_override_bridge_node.py`
- `src/seano_vision/seano_vision/mission_mode_manager_node.py`

Hardware-sensitive surfaces touched by the patch:

- Collision-risk threshold defaults.
- Watchdog safe-command dwell behavior.
- HUD/debug-image state display and `/ca/metrics` fields.

Hardware-sensitive surfaces not changed:

- `run_phase7_monitor_no_log.sh` still passes `use_mavros:=false`.
- Phase 7 launch does not start MAVProxy.
- `ca_det_publish_annotated:=false` is preserved in the formal runner.
- `actuator_interface_confirmed:=true` is preserved in the formal runner and remains a valid launch argument.
- MAVROS topic names, RC override topic names, RC channel mapping, PWM calibration, and manual-authority release gates are unchanged.

## Relevant Files And Functions

### `risk_evaluator_node.py`

- Computes track risk in `_evaluate()`.
- Classifies operator risk bands through `risk_policy.classify_risk()` after patch.
- Selects raw CA command in `_decide_command()`.
- Publishes `/ca/risk`, `/ca/command`, `/ca/mode`, `/ca/avoid_active`, `/ca/metrics`, and `/ca/debug_image` in `_process_once()`.
- Generates HUD in `_publish_debug_overlay()` and `_draw_hud()`.
- Computes `/ca/avoid_active` decision in `_compute_final_avoid_active()` and `_govern_avoid_active()`.

### `watchdog_failsafe_node.py`

- Subscribes `/ca/risk`, `/ca/mode`, `/ca/command`.
- Publishes `/ca/command_safe`, `/ca/failsafe_active`, `/ca/failsafe_reason`, `/ca/watchdog_status`.
- Rewrites commands on stale/lost/caution state in `_on_tick()`.
- Applies final safe-command dwell in `_apply_command_dwell()`.

### `auto_controller_stub_node.py`

- Runtime role is Auto Takeover Manager.
- Subscribes `/ca/command_safe` and `/ca/failsafe_active`.
- Publishes `/seano/auto/left_cmd`, `/seano/auto/right_cmd`, `/seano/auto_enable`, `/seano/rc_override_enable`.
- Treats `SLOW_DOWN`, `TURN_LEFT_SLOW`, `TURN_RIGHT_SLOW`, `STOP`, `TURN_LEFT`, and `TURN_RIGHT` as hazard/takeover commands.

### `command_mux_node.py`

- Selects manual vs auto left/right commands from `/seano/auto_enable`.
- Publishes `/seano/selected/left_cmd` and `/seano/selected/right_cmd`.

### `actuator_safety_limiter_node.py`

- Applies failsafe, input timeout, clamp, and slew after the mux.
- Publishes final normalized `/seano/left_cmd` and `/seano/right_cmd`.

### `mavros_rc_override_bridge_node.py`

- Subscribes final normalized commands and `/seano/rc_override_enable`.
- Blocks/releases override when `/seano/operator_manual_authority` is true or stale.
- Blocks active output when actuator interface is not confirmed ready.
- Publishes `/mavros/rc/override` release or active PWM override.

### `mission_mode_manager_node.py`

- Subscribes `/seano/rc_override_enable`, `/ca/failsafe_active`, `/ca/avoid_active`, `/mavros/state`.
- Publishes `/ca/mode_manager_state`, `/ca/mode_manager_event`, and `/seano/operator_manual_authority`.
- Uses `/seano/rc_override_enable` as strongest evidence for AVOID state.

## Current Risk Thresholds Found

Before patch:

- `risk_evaluator_node.py`
  - `enter_avoid_risk = 0.55`
  - `exit_avoid_risk = 0.35`
  - `risk_slow_threshold = 0.45`
  - `risk_turn_slow_threshold = 0.55`
  - `risk_turn_threshold = 0.75`
  - `risk_stop_threshold = 0.92`
  - `avoid_active_enter_risk = 0.45`
  - `avoid_active_exit_risk = 0.20`
  - HUD color split used `0.35` and `0.70`

- `watchdog_failsafe_node.py`
  - `avoid_command_risk_threshold = 0.55`
  - `avoid_command_stop_threshold = 0.92`
  - `avoid_command_release_risk = 0.35`

After patch, shared defaults are centralized in `src/seano_vision/seano_vision/risk_policy.py`:

- `LOW_RISK_MAX = 0.30`
- `HIGH_RISK_MIN = 0.60`
- `EMERGENCY_STOP_RISK = 0.92`
- `RELEASE_RISK_MAX = 0.25`

Default bands now match the Phase 7 operator policy:

- `LOW`: `0.00 <= Rmax < 0.30`
- `MEDIUM`: `0.30 <= Rmax < 0.60`
- `HIGH`: `Rmax >= 0.60`

## Current Command Mapping Found

Raw command selection starts in `risk_evaluator_node.py::_decide_command()`:

- Invalid/missing geometry outside startup grace: `STOP`.
- `LOST_PERCEPTION`: `STOP`.
- No target: `HOLD_COURSE`.
- Low risk below `0.30`: `HOLD_COURSE`.
- Medium risk `0.30 <= R < 0.60`: `SLOW_DOWN` or `TURN_*_SLOW` depending situation/corridor/urgency.
- High risk `R >= 0.60`: `TURN_LEFT`/`TURN_RIGHT`, or `STOP` at emergency stop threshold/TTC emergency.

Safe command selection continues in `watchdog_failsafe_node.py`:

- LOST/stale required inputs: `STOP` and `/ca/failsafe_active=true`.
- CAUTION: caps full turns to slow turns or slow command.
- Normal: forwards raw command unless dwell applies.
- Patched dwell keeps incoming avoid commands latched but no longer escalates medium risk to `STOP` merely because risk crossed the dwell threshold. `STOP` remains forced at `EMERGENCY_STOP_RISK`.

Takeover mapping in `auto_controller_stub_node.py`:

- `HOLD_COURSE` or empty command: release after clear hold and minimum takeover time.
- `SLOW_DOWN`, `TURN_LEFT_SLOW`, `TURN_RIGHT_SLOW`, `STOP`, `TURN_LEFT`, `TURN_RIGHT`: publish auto commands, `/seano/auto_enable=true`, `/seano/rc_override_enable=true`.
- Failsafe: STOP takeover, not release.
- Master disabled: release.

Bridge mapping in `mavros_rc_override_bridge_node.py`:

- `/seano/rc_override_enable=false`: publish RC release.
- Operator manual authority true or stale: publish RC release.
- Interface not ready: publish RC release.
- Otherwise publish active RC override to configured channels.

## Current HUD Source Of Truth

Before patch, `/ca/debug_image` HUD was generated only by `risk_evaluator_node.py` from evaluator-local metrics:

- `CMD` came from raw `/ca/command`.
- `AVOID` came from local `avoid_mode`.
- HUD did not subscribe to `/ca/command_safe`, `/seano/auto_enable`, `/seano/rc_override_enable`, `/ca/mode_manager_state`, `/seano/operator_manual_authority`, or bridge interface status.

After patch, the HUD still renders in `risk_evaluator_node.py`, but mirrors downstream state for display/logging:

- `command_raw`
- `command_safe`
- `command_selected`
- `risk_raw`
- `risk_class`
- `ca_active`
- `avoid_active_decision`
- `takeover_active`
- `auto_enable`
- `failsafe_active`
- `mode_manager_state`
- `operator_manual_authority`
- `operator_manual_authority_stale`
- `override_state`
- `override_active`
- `override_blocked`
- `actuator_interface_ready`
- `source_timestamp`
- `source_age_s`
- per-topic `sync_ages_s`

## Current Actuator/Override Source Of Truth

The actuator path is:

`/ca/command` -> watchdog `/ca/command_safe` -> takeover manager -> `/seano/auto_enable` and `/seano/rc_override_enable` -> command mux -> limiter -> MAVROS RC override bridge.

The strongest available software evidence of takeover request is `/seano/rc_override_enable`. Actual bridge output can still be blocked/released by:

- `/seano/operator_manual_authority == true`
- stale `/seano/operator_manual_authority`
- actuator interface not ready/confirmed
- stale final command inputs
- node disabled

## HUD/Actuator Divergence Finding

Before patch, HUD and actuator could diverge.

Primary divergence:

- `risk_evaluator_node.py` entered local `avoid_mode` at `0.55`.
- Raw `SLOW_DOWN` could be selected below that, originally from `risk_slow_threshold=0.45`.
- `auto_controller_stub_node.py` treats `SLOW_DOWN` as a hazard/takeover command.
- Result: `/seano/rc_override_enable=true` and actual override request could occur while HUD still showed `AVOID: OFF`.

Secondary divergence:

- Watchdog dwell could publish `/ca/command_safe=STOP` while HUD still displayed raw `/ca/command`.
- During dwell/release delays, takeover could remain active after evaluator-local `avoid_mode` cleared.

Timestamp/staleness divergence:

- HUD image selection pairs metrics with a buffered image by detection stamp, bounded by `max_image_age_s=0.40`.
- HUD previously did not show downstream topic ages, so stale command or override state could not be diagnosed from the image alone.
- Web video streaming can add latency, but the code-level source-of-truth split is enough to explain the field symptom.

## Root-Cause Hypothesis

The field symptom "actual override active but HUD AVOID still OFF" is most likely caused by the HUD using evaluator-local `avoid_mode` rather than the actuator path state. Medium/early hazard commands can activate the takeover manager through `/ca/command_safe`, `/seano/auto_enable`, and `/seano/rc_override_enable` before local HUD `avoid_mode` reaches its old entry threshold. Watchdog dwell can also keep the actuator path active after raw evaluator state has changed.

## Minimal Patch Applied

- Added shared risk-band constants in `risk_policy.py`.
- Updated risk evaluator defaults to `LOW < 0.30`, `MEDIUM 0.30..<0.60`, `HIGH >= 0.60`.
- Updated watchdog dwell defaults to the shared policy.
- Changed watchdog dwell so medium risk does not automatically become `STOP`; it latches the incoming avoid command and reserves forced `STOP` for emergency risk.
- Added downstream HUD sync subscriptions in `risk_evaluator_node.py`.
- Added explicit `/ca/metrics` fields and throttled `phase7_sync` log lines for risk, command, avoid, takeover, override, source timestamp, and ages.
- Updated HUD text to show selected/safe/raw command, CA activity, takeover, override state, manual authority, mode-manager state, risk class, source, and source age.
- Added `scripts/check_phase7_sync_log.py` to scan `terminal_log.txt` for sync inconsistencies.

## Remaining Risks

- The HUD now depends on downstream topic receipt for display truth; if a downstream topic is stale, HUD marks it stale/unknown rather than assuming active.
- `source_age_s` is process age for the current risk evaluation, not end-to-end camera-to-browser stream latency.
- Actual FCU behavior still requires hardware evidence from `/mavros/rc/override`, `/mavros/state`, and RC input/output monitoring.
- The untracked `phase7_mode_authority_bridge.py` exists in the workspace root and is required by the stated field policy, but this patch does not install or launch it.

## Next Recommended Action

Run the formal WSL-safe verification:

```bash
python3 -m compileall -q src/seano_vision/seano_vision src/seano_vision/launch
```

Then, after the next field run, scan the terminal log:

```bash
python3 scripts/check_phase7_sync_log.py terminal_log.txt
```
