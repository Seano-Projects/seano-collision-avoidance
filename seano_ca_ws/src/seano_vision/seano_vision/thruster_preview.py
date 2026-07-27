"""Pure, hardware-free policy and thruster preview helpers."""

from __future__ import annotations

from dataclasses import dataclass

from .risk_policy import (
    CMD_HOLD,
    CMD_SLOW,
    CMD_STOP,
    CMD_TURN_LEFT,
    CMD_TURN_LEFT_SLOW,
    CMD_TURN_RIGHT,
    CMD_TURN_RIGHT_SLOW,
    normalize_command_details,
)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


@dataclass(frozen=True)
class PoolDecision:
    command: str
    obstacle_side: str
    selected_direction: str
    reason: str


def select_pool_turn_away_command(
    *, risk: float, x_ratio: float, center_band_ratio: float,
    slow_threshold: float, turn_threshold: float, stop_threshold: float,
    very_close: bool = False, valid: bool = True, lost_perception: bool = False,
) -> PoolDecision:
    """Select an image-side turn-away command for the opt-in pool profile."""
    if not valid or lost_perception:
        return PoolDecision(CMD_STOP, "UNKNOWN", "STOP", "INVALID_OR_LOST_PERCEPTION")
    x = clamp(x_ratio, 0.0, 1.0)
    half_center = clamp(center_band_ratio, 0.0, 1.0) / 2.0
    side = "CENTER" if abs(x - 0.5) <= half_center else ("PORT" if x < 0.5 else "STARBOARD")
    if risk >= stop_threshold or (side == "CENTER" and very_close):
        return PoolDecision(CMD_STOP, side, "STOP", "CRITICAL_OR_CENTER_CLOSE")
    if risk < slow_threshold:
        return PoolDecision(CMD_HOLD, side, "HOLD", "LOW_RISK")
    if side == "CENTER":
        command = CMD_SLOW if risk < turn_threshold else CMD_STOP
        return PoolDecision(command, side, "STRAIGHT" if command == CMD_SLOW else "STOP", "CENTER_OBSTACLE")
    slow = risk < turn_threshold
    if side == "STARBOARD":
        return PoolDecision(CMD_TURN_LEFT_SLOW if slow else CMD_TURN_LEFT, side, "PORT", "TURN_AWAY")
    return PoolDecision(CMD_TURN_RIGHT_SLOW if slow else CMD_TURN_RIGHT, side, "STARBOARD", "TURN_AWAY")


def command_to_left_right(
    command: str, *, cruise_speed: float = 0.30, slow_factor: float = 0.55,
    turn_speed_factor: float = 0.75, turn_cmd: float = 0.50,
    diff_mix_gain: float = 0.65, speed_max: float = 0.55,
    turn_max: float = 1.0, allow_reverse: bool = False,
) -> tuple[float, float, bool]:
    """Convert a command to normalized differential thrust; unknown fails STOP."""
    cmd, known, _ = normalize_command_details(command)
    speed = turn = 0.0
    if cmd == CMD_SLOW:
        speed = cruise_speed * slow_factor
    elif cmd in (CMD_TURN_LEFT, CMD_TURN_LEFT_SLOW):
        speed = cruise_speed * (turn_speed_factor if cmd == CMD_TURN_LEFT else slow_factor)
        turn = -abs(turn_cmd)
    elif cmd in (CMD_TURN_RIGHT, CMD_TURN_RIGHT_SLOW):
        speed = cruise_speed * (turn_speed_factor if cmd == CMD_TURN_RIGHT else slow_factor)
        turn = abs(turn_cmd)
    elif cmd in (CMD_HOLD, CMD_STOP):
        speed = 0.0
    speed = clamp(speed, -speed_max if allow_reverse else 0.0, speed_max)
    turn = clamp(turn, -turn_max, turn_max)
    left = speed + diff_mix_gain * turn
    right = speed - diff_mix_gain * turn
    bounds = (-1.0, 1.0) if allow_reverse else (0.0, 1.0)
    return clamp(left, *bounds), clamp(right, *bounds), known


def normalized_to_preview(left: float, right: float, maximum_throttle_percent: float = 100.0,
                          maximum_steering_percent: float = 100.0) -> dict:
    throttle = clamp(100.0 * (left + right) / 2.0, -abs(maximum_throttle_percent), abs(maximum_throttle_percent))
    steering = clamp(100.0 * (left - right) / 2.0, -abs(maximum_steering_percent), abs(maximum_steering_percent))
    pwm_ch1 = int(round(clamp(1500.0 + (-steering / 100.0) * 500.0, 1000.0, 2000.0)))
    pwm_ch3 = int(round(clamp(1500.0 + (throttle / 100.0) * 500.0, 1000.0, 2000.0)))
    return {"throttle": throttle, "steering": steering, "pwm_ch1": pwm_ch1, "pwm_ch3": pwm_ch3}


def evaluate_actuator_path_ready(*, enabled: bool, left_fresh: bool, right_fresh: bool,
                                 command_fresh: bool, failsafe_active: bool, dry_run: bool,
                                 external_interface_confirmed: bool,
                                 external_arbitration_confirmed: bool,
                                 hardware_output_enabled: bool) -> tuple[bool, str]:
    checks = [
        (enabled, "ADAPTER_DISABLED"), (left_fresh, "LEFT_INPUT_STALE"),
        (right_fresh, "RIGHT_INPUT_STALE"), (command_fresh, "SAFE_COMMAND_STALE"),
        (not failsafe_active, "FAILSAFE_ACTIVE"), (not dry_run, "DRY_RUN"),
        (external_interface_confirmed, "EXTERNAL_INTERFACE_NOT_CONFIRMED"),
        (external_arbitration_confirmed, "EXTERNAL_ARBITRATION_NOT_CONFIRMED"),
        (hardware_output_enabled, "HARDWARE_OUTPUT_DISABLED"),
    ]
    reasons = [reason for ok, reason in checks if not ok]
    return not reasons, "READY" if not reasons else ";".join(reasons)


def takeover_request_allowed(actuator_path_ready: bool, require_ready: bool = True) -> bool:
    return bool(actuator_path_ready) or not bool(require_ready)


def actuator_path_gate_open(
    *, actuator_path_ready: bool, ready_received_at: float, now: float,
    timeout_s: float, require_ready: bool,
) -> bool:
    """Fail closed when a required readiness value was never seen or is stale."""
    if not require_ready:
        return True
    if not actuator_path_ready or ready_received_at <= 0.0:
        return False
    return 0.0 <= (float(now) - float(ready_received_at)) <= max(0.01, float(timeout_s))
