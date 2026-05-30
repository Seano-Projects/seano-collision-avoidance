#!/usr/bin/env python3
"""Render a compact live view from raw Phase 7 ROS terminal output.

Raw input is read from stdin and a filtered, line-buffered summary is written
to stdout. Malformed lines are ignored unless they contain WARN/ERROR content.
"""

from __future__ import annotations

from datetime import datetime
import re
import sys
from typing import Dict, Iterable, Optional


TOKEN_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=([^ \n|]+)")
WATCHDOG_RE = re.compile(r"\[WATCHDOG\]\s+STATE\s+->\s+([A-Za-z0-9_ -]+)")
ROS_NODE_RE = re.compile(r"\[[A-Z]+\]\s+\[[^\]]+\]\s+\[([^\]]+)\]:\s*(.*)")


IMPORTANT_LEVELS = ("[WARN]", "[ERROR]", "[FATAL]")
BRIDGE_TOKENS = (
    "RC_OVERRIDE_READY",
    "RC_OVERRIDE_RELEASE",
    "ACTUATOR_BLOCKED",
    "OPERATOR_MANUAL_AUTHORITY",
    "TIMEOUT->neutral",
    "PWM steer=",
    "active_output_blocked",
    "override_blocked",
    "override_disabled",
)


def configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass


def now_text() -> str:
    return datetime.now().strftime("%H:%M:%S")


def tokens(line: str) -> Dict[str, str]:
    return dict(TOKEN_RE.findall(line))


def node_and_message(line: str) -> tuple[str, str]:
    match = ROS_NODE_RE.search(line)
    if not match:
        return "", line.strip()
    return match.group(1), match.group(2).strip()


def get(row: Dict[str, str], key: str, default: str = "-") -> str:
    value = row.get(key, default)
    return value if value != "" else default


def compact_message(line: str, limit: int = 180) -> str:
    _node, message = node_and_message(line)
    text = " ".join(message.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def render_phase7_sync(line: str) -> str:
    row = tokens(line)
    return (
        f"{now_text()} SYNC "
        f"risk={get(row, 'risk_raw')} {get(row, 'risk_class')} "
        f"raw={get(row, 'raw_command', get(row, 'command_raw'))} "
        f"safe={get(row, 'safe_command', get(row, 'command_safe'))} "
        f"sel={get(row, 'selected_command', get(row, 'command_selected'))} "
        f"src={get(row, 'command_source')} "
        f"latched={get(row, 'command_latched')} "
        f"policy={get(row, 'command_policy_valid')} "
        f"auto={get(row, 'auto_enable')} "
        f"avoid={get(row, 'avoid_active')} "
        f"takeover={get(row, 'takeover_active')} "
        f"override={get(row, 'override_active')} "
        f"blocked={get(row, 'override_blocked')} "
        f"manual={get(row, 'operator_manual_authority')}"
    )


def render_detector(line: str) -> Optional[str]:
    if "det=" not in line or "proc_ema=" not in line:
        return None
    row = tokens(line)
    proc = get(row, "proc_ema")
    if proc != "-" and not proc.endswith("ms"):
        proc = f"{proc}ms"
    parts = [
        f"{now_text()} DET",
        f"det={get(row, 'det')}",
        f"proc={proc}",
        f"frames={get(row, 'frames')}",
    ]
    if "conf" in row:
        parts.append(f"conf={row['conf']}")
    if "imgsz" in row:
        parts.append(f"imgsz={row['imgsz']}")
    return " ".join(parts)


def render_camera(line: str) -> Optional[str]:
    if "cap_fps=" not in line or "pub_fps=" not in line:
        return None
    row = tokens(line)
    parts = [
        f"{now_text()} CAM",
        f"cap={get(row, 'cap_fps')}",
        f"pub={get(row, 'pub_fps')}",
    ]
    if "age" in row:
        parts.append(f"age={row['age']}")
    if "source" in row:
        parts.append(f"source={row['source']}")
    if "input" in row:
        parts.append(f"input={row['input']}")
    elif "device" in row:
        parts.append(f"device={row['device']}")
    return " ".join(parts)


def render_watchdog(line: str) -> Optional[str]:
    match = WATCHDOG_RE.search(line)
    if not match:
        return None
    return f"{now_text()} WATCHDOG state={match.group(1).strip()}"


def render_bridge(line: str) -> Optional[str]:
    node, _message = node_and_message(line)
    if node and node != "mavros_rc_override_bridge_node":
        return None
    if not any(token in line for token in BRIDGE_TOKENS):
        return None
    return f"{now_text()} BRIDGE {compact_message(line)}"


def render_limiter(line: str) -> Optional[str]:
    node, _message = node_and_message(line)
    text = line.lower()
    if node != "actuator_safety_limiter_node" and "actuator_safety_limiter" not in text:
        return None
    if not ("out " in text or "failsafe" in text or "fs_age" in text):
        return None
    return f"{now_text()} LIMIT {compact_message(line)}"


def render_warning_or_error(line: str) -> Optional[str]:
    if not any(level in line for level in IMPORTANT_LEVELS):
        return None
    level = "ERROR" if "[ERROR]" in line or "[FATAL]" in line else "WARN"
    return f"{now_text()} {level} {compact_message(line, limit=220)}"


def render_runner(line: str) -> Optional[str]:
    stripped = line.strip()
    if stripped.startswith("[RUN]") or stripped.startswith("[WARN]"):
        return stripped
    return None


def render_line(line: str) -> Optional[str]:
    try:
        if "phase7_sync " in line:
            return render_phase7_sync(line)
        for renderer in (
            render_detector,
            render_camera,
            render_watchdog,
            render_bridge,
            render_limiter,
            render_warning_or_error,
            render_runner,
        ):
            rendered = renderer(line)
            if rendered:
                return rendered
    except Exception as exc:
        return f"{now_text()} WARN pretty_live parse_error={type(exc).__name__}"
    return None


def main(lines: Iterable[str]) -> int:
    configure_stdout()
    for line in lines:
        rendered = render_line(line)
        if rendered:
            print(rendered, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.stdin))
