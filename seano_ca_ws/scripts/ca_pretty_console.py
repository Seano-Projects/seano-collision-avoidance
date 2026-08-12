#!/usr/bin/env python3

import re
import sys


USE_COLOR = sys.stdout.isatty()

RESET = "\033[0m" if USE_COLOR else ""
GREEN = "\033[1;32m" if USE_COLOR else ""
BLUE = "\033[1;34m" if USE_COLOR else ""
CYAN = "\033[1;36m" if USE_COLOR else ""
YELLOW = "\033[1;33m" if USE_COLOR else ""
RED = "\033[1;31m" if USE_COLOR else ""
DIM = "\033[2m" if USE_COLOR else ""

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

actuator_warning_shown = False
yolo_warning_shown = False
failsafe_warning_shown = False


def clean(line: str) -> str:
    return ANSI_RE.sub("", line).strip()


def shorten(text: str, limit: int = 220) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def emit(color: str, tag: str, text: str) -> None:
    print(f"{color}{tag:<10}{RESET} {text}", flush=True)


for raw in sys.stdin:
    line = clean(raw)

    if not line:
        continue

    # ========================================================
    # ERROR / FATAL
    # ========================================================

    # FAILSAFE STOP adalah safety event yang diketahui, bukan
    # generic application crash.
    if "FAILSAFE ACTIVE -> TAKEOVER STOP" in line:
        if not failsafe_warning_shown:
            emit(
                YELLOW,
                "[SAFETY]",
                "Failsafe active; STOP selected and hardware motion remains gated",
            )
            failsafe_warning_shown = True
        continue

    if any(
        token in line
        for token in (
            "AUTO TAKEOVER ABORT",
            "[FATAL]",
            "Traceback",
            "RuntimeError",
            "process has died",
        )
    ):
        emit(RED, "[ERROR]", shorten(line))
        continue

    if "[ERROR]" in line:
        emit(RED, "[ERROR]", shorten(line))
        continue

    # ========================================================
    # PREFLIGHT / STARTUP
    # ========================================================

    if "Ready for guarded AUTO takeover procedure: true" in line:
        emit(GREEN, "[READY]", "Preflight passed")
        continue

    if "[HUD] Checking port 8080" in line:
        emit(BLUE, "[HUD]", "Checking web video service on port 8080")
        continue

    if "Session-owned web_video_server ready" in line:
        emit(GREEN, "[READY]", "Web video server ready on port 8080")
        continue

    if "Operator confirmation already completed" in line:
        emit(GREEN, "[READY]", "Operator confirmation accepted")
        continue

    if line.startswith("AUTO TAKEOVER SESSION:"):
        session = line.split("AUTO TAKEOVER SESSION:", 1)[1].strip()
        emit(CYAN, "[SESSION]", session)
        continue

    if line.startswith("HUD_URL="):
        emit(CYAN, "[HUD]", line.split("=", 1)[1])
        continue

    if "web_video_available=true" in line:
        emit(GREEN, "[READY]", "HUD web video available")
        continue

    if "External MAVROS and /usv/thruster are reused" in line:
        emit(
            BLUE,
            "[SYSTEM]",
            "External MAVROS + /usv/thruster active; internal RC bridge disabled",
        )
        continue

    if "Safe stop: Ctrl+C" in line:
        emit(BLUE, "[SYSTEM]", "Ctrl+C stops this CA session safely")
        continue

    # ========================================================
    # VISION
    # ========================================================

    if "Capture opened" in line:
        emit(GREEN, "[VISION]", "Camera opened successfully")
        continue

    if "YOLO warmup done" in line:
        emit(GREEN, "[VISION]", "YOLOv8n TensorRT warmup completed")
        continue

    if (
        "detector_node" in line
        and "Started" in line
        and "classes=ALL" in line
    ):
        emit(GREEN, "[VISION]", "Object detector ready")
        continue

    if "automatically guess model task" in line:
        if not yolo_warning_shown:
            emit(
                BLUE,
                "[VISION]",
                "Ultralytics model-task auto detection notice (non-fatal)",
            )
            yolo_warning_shown = True
        continue

    # ========================================================
    # WATCHDOG / FAILSAFE
    # ========================================================

    if "[WATCHDOG] STATE -> LOST" in line:
        emit(YELLOW, "[SAFETY]", "Perception watchdog -> LOST")
        continue

    if "[WATCHDOG] STATE -> NORMAL" in line:
        emit(GREEN, "[READY]", "Perception watchdog -> NORMAL")
        actuator_warning_shown = False
        failsafe_warning_shown = False
        continue

    if "ACTUATOR_PATH_NOT_READY" in line:
        if not actuator_warning_shown:
            emit(
                YELLOW,
                "[SAFETY]",
                "Actuator path not ready; hardware motion remains blocked",
            )
            actuator_warning_shown = True
        continue

    if "FAILSAFE ACTIVE -> TAKEOVER STOP" in line:
        if not failsafe_warning_shown:
            emit(
                YELLOW,
                "[SAFETY]",
                "Failsafe active; STOP selected and motion remains safety-gated",
            )
            failsafe_warning_shown = True
        continue

    # ========================================================
    # IMPORTANT CA STATES
    # ========================================================

    state_keywords = (
        "AUTO_MISSION_MONITORING",
        "OPERATOR_OVERRIDE",
        "TAKEOVER_REQUESTED",
        "WAITING_FOR_MANUAL_CONFIRMATION",
        "AVOIDANCE_READY",
        "MOTION_COMMAND_PENDING",
        "MOTION_ACTIVE",
        "STOP_ACTIVE",
        "CLEAR_HOLD",
        "RELEASING_CONTROL",
        "AUTO_RESTORE",
        "AUTO_REJOIN",
        "RETURNED_TO_AUTO",
        "MISSION_COMPLETE",
        "ABORTED",
    )

    if any(keyword in line for keyword in state_keywords):
        emit(CYAN, "[STATE]", shorten(line))
        continue

    # ========================================================
    # OTHER WARNINGS
    # ========================================================

    if (
        "Thruster adapter PREVIEW only" in line
        or "GUARDED hardware-test adapter loaded" in line
    ):
        continue

    if "[WARN]" in line or "WARNING" in line:
        emit(YELLOW, "[WARN]", shorten(line))
        continue

    # ========================================================
    # DROP HIGH-FREQUENCY TELEMETRY
    # ========================================================

    drop_patterns = (
        "phase7_sync",
        "camera_hp]: stats",
        "detector_node]: det=",
        "auto_controller_stub_node]: state=",
        "command_mux_node]: [OK]",
        "command_mux_node]: [FAILSAFE_STOP]",
        "actuator_safety_limiter_node]: reason=",
        "event_logger_node]: event |",
        "[TRT] [I]",
        "TensorRT inference",
        "process started with pid",
        "[launch]",
    )

    if any(pattern in line for pattern in drop_patterns):
        continue

    # ========================================================
    # DROP VERBOSE PREFLIGHT DETAILS
    # ========================================================

    preflight_prefixes = (
        "AUTO TAKEOVER PREFLIGHT ONLY",
        "No ROS node started",
        "ROS_DOMAIN_ID:",
        "FCU connected:",
        "FCU armed:",
        "FCU mode:",
        "Control state at startup",
        "CA control becomes eligible",
        "RC publisher",
        "MAVROS RC subscriber:",
        "MAVROS set_mode service:",
        "Runtime graph clear:",
        "MQTT credentials:",
        "TLS required:",
        "Limits conservative:",
    )

    if line.startswith(preflight_prefixes):
        continue

    # ========================================================
    # ORDINARY ROS INFO -> HIDE
    # ========================================================

    if "[INFO]" in line:
        continue

    # Unknown output tetap ditampilkan agar error baru tidak hilang.
    print(line, flush=True)
