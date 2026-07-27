"""Side-effect-free header renderer for the AUTO takeover runtime."""

from __future__ import annotations

from typing import Any, Mapping

import cv2
import numpy as np


HEADER_HEIGHT = 300
FONT = cv2.FONT_HERSHEY_SIMPLEX
SCALE = 0.32
THICKNESS = 1
MARGIN = 6


def _yn(value: Any) -> str:
    return "Y" if bool(value) else "N"


def _num(value: Any, precision: int = 1) -> str:
    try:
        return f"{float(value):.{precision}f}"
    except (TypeError, ValueError):
        return "-"


def _short(value: Any, limit: int = 12) -> str:
    text = str(value or "-")
    return text if len(text) <= limit else text[:limit]


def _fit(text: str, width: int) -> str:
    if cv2.getTextSize(text, FONT, SCALE, THICKNESS)[0][0] <= width:
        return text
    value = text
    while value:
        candidate = value.rstrip() + "..."
        if cv2.getTextSize(candidate, FONT, SCALE, THICKNESS)[0][0] <= width:
            return candidate
        value = value[:-1]
    return "..."


def header_lines(status: Mapping[str, Any], width: int) -> tuple[str, ...]:
    usable = max(1, int(width) - 2 * MARGIN)
    slow_command = str(status.get("mapped_command", "")).upper() in {
        "SLOW_DOWN",
        "TURN_LEFT_SLOW",
        "TURN_RIGHT_SLOW",
    }
    slow_delivered = slow_command and bool(
        status.get("command_published")
        or status.get("mqtt_ack_received")
        or status.get("mqtt_own_echo_received")
        or status.get("rc_command_delivered")
    )
    lines = (
        f"AUTO TAKEOVER | STATE:{status.get('state', 'STARTING')} "
        f"| SESSION:{_short(status.get('session_id'))}",
        f"CYCLE_ID:{status.get('cycle_id', 0)} "
        f"| COMPLETED_CYCLES:{status.get('completed_cycle_count', 0)} "
        f"| MISSION ACTIVE:{_yn(status.get('mission_active', True))}",
        f"FCU MODE:{status.get('fcu_mode', '?')} "
        f"| ORIGINAL MODE:{status.get('original_mode') or '-'} "
        f"| OWNER:{_yn(status.get('takeover_owner'))}",
        f"DESIRED:{_short(status.get('desired_command'), 18)} "
        f"| MAPPED:{_short(status.get('mapped_command'), 18)} "
        f"| PUBLISHED:{_yn(status.get('command_published'))}",
        f"NEUTRAL SENT:{_yn(status.get('neutral_sent'))} "
        f"| RELEASE SENT:{_yn(status.get('release_sent'))} "
        f"| RELEASE ECHO:{_yn(status.get('release_own_echo_received'))}",
        f"AUTO REQUEST COUNT:{status.get('auto_request_count', 0)} "
        f"| AUTO SERVICE RESPONSE:"
        f"{status.get('auto_service_response', 'NONE')}",
        f"AUTO MODE OBSERVED:{_yn(status.get('auto_mode_observed'))} "
        f"| AUTO RESTORE PENDING:"
        f"{_yn(status.get('auto_restore_pending'))} "
        f"| AUTO REJOIN VERIFIED:"
        f"{_yn(status.get('auto_rejoin_verified'))}",
        f"MQTT ACK:{_yn(status.get('mqtt_ack_received'))} "
        f"| OWN ECHO:{_yn(status.get('mqtt_own_echo_received'))} "
        f"| RC DELIVERED:{_yn(status.get('rc_command_delivered'))}",
        f"THROTTLE:{_num(status.get('requested_throttle'))}% "
        f"| STEERING:{_num(status.get('requested_steering'))}% "
        f"| MOTION:{_yn(status.get('motion_allowed'))}",
        f"REQ PWM CH1:{status.get('requested_steering_pwm') or '-'} "
        f"CH3:{status.get('requested_throttle_pwm') or '-'} "
        f"| OBS CH1:{status.get('observed_steering_pwm') or '-'} "
        f"CH3:{status.get('observed_throttle_pwm') or '-'}",
        f"WATCHDOG:{_num(status.get('motion_watchdog_age_s'))}/"
        f"{_num(status.get('command_freshness_watchdog_s'))}s "
        f"| CLEAR:{_num(status.get('clear_elapsed_s'))}s",
        f"REASON:{status.get('operational_reason') or '-'}",
        f"SLOW COMMAND DELIVERED:{_yn(slow_delivered)} "
        f"| SLOW PHYSICAL EFFECT:UNVERIFIED",
        f"BLOCKED REASON:{status.get('blocked_reason') or '-'}",
        f"ABORT REASON:{status.get('abort_reason') or '-'}",
    )
    return tuple(_fit(line, usable) for line in lines)


def render_auto_takeover_header(
    frame: np.ndarray,
    status: Mapping[str, Any],
) -> np.ndarray:
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("AUTO takeover HUD input must be BGR")
    height, width = frame.shape[:2]
    output = np.full((height + HEADER_HEIGHT, width, 3), (16, 18, 22), dtype=frame.dtype)
    output[HEADER_HEIGHT:] = frame
    colors = (
        (70, 70, 255) if status.get("abort_reason") else (0, 220, 255),
        (235, 235, 235),
        (80, 220, 100) if status.get("physical_ready") else (0, 220, 255),
        (235, 235, 235),
        (235, 235, 235),
        (0, 220, 255),
        (80, 220, 100) if status.get("auto_rejoin_verified") else (0, 220, 255),
        (80, 220, 100) if status.get("rc_command_delivered") else (0, 220, 255),
        (235, 235, 235),
        (235, 235, 235),
        (0, 220, 255),
        (
            (80, 220, 100)
            if status.get("operational_reason") == "NORMAL_NO_OBSTACLE"
            else (70, 70, 255)
        ),
        (0, 220, 255),
        (235, 235, 235),
        (70, 70, 255) if status.get("abort_reason") else (235, 235, 235),
    )
    for line, color, y in zip(
        header_lines(status, width),
        colors,
        tuple(range(16, 16 + 19 * 15, 19)),
    ):
        cv2.putText(output, line, (MARGIN, y), FONT, SCALE, color, THICKNESS, cv2.LINE_AA)
    cv2.line(output, (0, HEADER_HEIGHT - 1), (width - 1, HEADER_HEIGHT - 1), (90, 90, 100), 1)
    return output
