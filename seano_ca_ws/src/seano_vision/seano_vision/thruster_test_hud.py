"""Pure renderer for the compact hardware-test header.

The input image is copied unchanged below a new solid header.  This module has
no ROS, MQTT, MAVROS, or hardware side effects so its pixel behavior can be
tested with synthetic frames.
"""

from __future__ import annotations

from typing import Any, Mapping

import cv2
import numpy as np


HEADER_HEIGHT = 96
HEADER_MARGIN_X = 8
FONT_FACE = cv2.FONT_HERSHEY_SIMPLEX
FONT_SCALE = 0.38
FONT_THICKNESS = 1

COLOR_BACKGROUND = (18, 18, 22)
COLOR_TEXT = (235, 235, 235)
COLOR_GREEN = (80, 220, 100)
COLOR_YELLOW = (0, 220, 255)
COLOR_RED = (70, 70, 255)
COLOR_SEPARATOR = (90, 90, 100)

STATUS_LABELS = {
    "STARTING": "STARTING",
    "WAITING_FOR_CA_READY": "WAIT_CA",
    "WAITING_FOR_OPERATOR_MODE": "WAIT_MODE",
    "WAITING_FOR_OPERATOR_ARM": "WAIT_ARM",
    "READY_FOR_OBSTACLE_TEST": "READY_TEST",
    "MOTION_ACTIVE": "MOTION",
    "ABORTED": "ABORTED",
    "ABORTED_FOREIGN_COMMAND": "ABORTED",
    "PREVIEW_ONLY": "PREVIEW",
}


def compact_status(status: Any) -> str:
    normalized = str(status or "").strip().upper()
    return STATUS_LABELS.get(normalized, normalized[:16] or "UNKNOWN")


def _yes_no(value: Any) -> str:
    return "YES" if bool(value) else "NO"


def _fit_text(text: Any, maximum_width: int) -> str:
    value = " ".join(str(text or "--").split())
    if maximum_width <= 0:
        return ""
    width = cv2.getTextSize(
        value, FONT_FACE, FONT_SCALE, FONT_THICKNESS
    )[0][0]
    if width <= maximum_width:
        return value
    ellipsis = "..."
    while value:
        candidate = value.rstrip() + ellipsis
        width = cv2.getTextSize(
            candidate, FONT_FACE, FONT_SCALE, FONT_THICKNESS
        )[0][0]
        if width <= maximum_width:
            return candidate
        value = value[:-1]
    return ellipsis


def header_lines(values: Mapping[str, Any], width: int) -> tuple[str, ...]:
    usable_width = max(1, int(width) - 2 * HEADER_MARGIN_X)
    status = compact_status(values.get("status"))
    motion = "ALLOWED" if bool(values.get("motion")) else "BLOCKED"
    mqtt = "OK" if bool(values.get("mqtt_connected")) else "DOWN"
    line_1 = (
        f"HARDWARE TEST | STATUS:{status} | FCU:{values.get('fcu_mode', 'UNKNOWN')} "
        f"| REQ:{values.get('required_mode', 'MANUAL')} "
        f"| ARMED:{_yes_no(values.get('fcu_armed'))}"
    )
    line_2 = (
        f"SW READY:{_yes_no(values.get('software_ready'))} "
        f"| PHYS READY:{_yes_no(values.get('physical_ready'))} "
        f"| MOTION:{motion} | MQTT:{mqtt} "
        f"| RC:{values.get('rc_publisher', 'UNAVAILABLE')}"
    )
    line_3 = (
        f"CMD:{values.get('command', 'NONE')} "
        f"| THR:{float(values.get('throttle', 0.0)):.1f}% "
        f"| STR:{float(values.get('steering', 0.0)):.1f}% "
        f"| CMD SENT:{_yes_no(values.get('motion_sent'))}"
    )

    reason_gap = 12
    reason_width = max(1, (usable_width - reason_gap) // 2)
    blocked = _fit_text(
        f"BLOCK:{values.get('blocked') or '--'}", reason_width
    )
    abort = _fit_text(
        f"ABORT:{values.get('abort') or '--'}", reason_width
    )
    line_4 = f"{blocked} | {abort}"
    return tuple(
        _fit_text(line, usable_width)
        for line in (line_1, line_2, line_3, line_4)
    )


def header_colors(values: Mapping[str, Any]) -> tuple[tuple[int, int, int], ...]:
    status = compact_status(values.get("status"))
    if status == "ABORTED" or values.get("abort"):
        status_color = COLOR_RED
    elif status in ("READY_TEST", "MOTION"):
        status_color = COLOR_GREEN
    else:
        status_color = COLOR_YELLOW

    readiness_color = (
        COLOR_GREEN if bool(values.get("physical_ready")) else COLOR_YELLOW
    )
    motion_color = (
        COLOR_GREEN
        if bool(values.get("motion")) or bool(values.get("motion_sent"))
        else COLOR_YELLOW
    )
    reason_color = (
        COLOR_RED
        if values.get("blocked") or values.get("abort")
        else COLOR_GREEN
    )
    return status_color, readiness_color, motion_color, reason_color


def render_hardware_header(
    frame: np.ndarray,
    values: Mapping[str, Any],
    header_height: int = HEADER_HEIGHT,
) -> np.ndarray:
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("hardware HUD input must be a BGR image")
    height, width = frame.shape[:2]
    header_height = int(header_height)
    if header_height < 70 or header_height > 100:
        raise ValueError("hardware HUD header height must be within 70..100 px")

    output = np.full(
        (height + header_height, width, 3),
        COLOR_BACKGROUND,
        dtype=frame.dtype,
    )
    output[header_height:, :, :] = frame
    cv2.line(
        output,
        (0, header_height - 1),
        (width - 1, header_height - 1),
        COLOR_SEPARATOR,
        1,
    )

    lines = header_lines(values, width)
    colors = header_colors(values)
    baselines = (19, 41, 63, 85)
    for line, color, baseline in zip(lines, colors, baselines):
        cv2.putText(
            output,
            line,
            (HEADER_MARGIN_X, baseline),
            FONT_FACE,
            FONT_SCALE,
            color,
            FONT_THICKNESS,
            cv2.LINE_AA,
        )
    return output
