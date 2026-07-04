#!/usr/bin/env python3
"""Render a compact live view from raw Phase 7 ROS terminal output.

Raw input is read from stdin and a filtered, line-buffered summary is written
to stdout. Tegrastats is read separately from PHASE7_TEGRASTATS_RAW so the raw
ROS launch log and raw tegrastats log remain separate evidence files.
"""

from __future__ import annotations

from datetime import datetime
import os
import re
import sys
import time
from typing import Dict, Iterable, List, Optional


TOKEN_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=([^ \n|]+)")
WATCHDOG_RE = re.compile(r"\[WATCHDOG\]\s+STATE\s+->\s+([A-Za-z0-9_ -]+)")
ROS_NODE_RE = re.compile(r"\[[A-Z]+\]\s+\[[^\]]+\]\s+\[([^\]]+)\]:\s*(.*)")

RAM_RE = re.compile(r"\bRAM\s+([0-9.]+)\/([0-9.]+)([KMG]B)?", re.IGNORECASE)
SWAP_RE = re.compile(r"\bSWAP\s+([0-9.]+)\/([0-9.]+)([KMG]B)?", re.IGNORECASE)
CPU_RE = re.compile(r"\bCPU\s+\[([^\]]+)\]", re.IGNORECASE)
CPU_LOAD_RE = re.compile(r"([0-9.]+)%")
GPU_RE = re.compile(r"\b(?:GR3D_FREQ|GR3D|GPU)\s+([0-9.]+)%", re.IGNORECASE)
TEMP_RE = re.compile(r"\b([A-Za-z0-9_]+)@([0-9.]+)C")
VDD_IN_RE = re.compile(r"\bVDD_IN\s+([0-9.]+)mW(?:\/([0-9.]+)mW)?")

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

CMD_W = 15
SRC_W = 14
SYNC_HEADER_INTERVAL = 20
DEFAULT_SYS_PERIOD_S = 5.0

# Legend for the abbreviated sync-table columns. BLK mirrors the
# override_blocked diagnostic field from /ca/metrics; it is not a fault
# status, only an internal signal about whether the RC-override bridge is
# currently withholding output (e.g. manual authority active, interface not
# yet confirmed). See PRD.md section 11 / AGENTS.md section 17.
SYNC_LEGEND = (
    "legend: LT=command_latched OK=command_policy_valid AUTO=auto_enable "
    "AVOID=avoid_active TAKE=takeover_active OVR=override_active "
    "BLK=override_blocked(diagnostic only, not a fault status) "
    "MAN=operator_manual_authority"
)


class PrettyState:
    def __init__(self) -> None:
        self.sync_count = 0
        self.last_sys_t = 0.0
        self.warned_missing_tegra = False
        self.warned_unparsed_tegra = False


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


def fit(value: str, width: int) -> str:
    text = str(value or "-")
    if len(text) <= width:
        return text
    return text[: width - 1] + "~"


def bool_cell(value: str) -> str:
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "y"}:
        return "Y"
    if text in {"0", "false", "no", "off", "n"}:
        return "N"
    return "-"


def compact_message(line: str, limit: int = 180) -> str:
    _node, message = node_and_message(line)
    text = " ".join(message.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def sync_header() -> str:
    return (
        f"{'TIME':<8} {'SRC':<5} {'RISK':>5} {'CLS':<6} "
        f"{'RAW':<{CMD_W}} {'SAFE':<{CMD_W}} {'SEL':<{CMD_W}} "
        f"{'CMD_SRC':<{SRC_W}} LT OK AUTO AVOID TAKE OVR BLK MAN"
    )


def render_phase7_sync(line: str, state: PrettyState) -> List[str]:
    row = tokens(line)
    state.sync_count += 1

    out: List[str] = []
    if state.sync_count > 1 and (state.sync_count - 1) % SYNC_HEADER_INTERVAL == 0:
        out.append(sync_header())
        out.append(SYNC_LEGEND)

    raw = get(row, "raw_command", get(row, "command_raw"))
    safe = get(row, "safe_command", get(row, "command_safe"))
    selected = get(row, "selected_command", get(row, "command_selected"))
    risk = get(row, "risk_raw")

    out.append(
        f"{now_text():<8} {'SYNC':<5} {risk:>5} {get(row, 'risk_class'):<6} "
        f"{fit(raw, CMD_W):<{CMD_W}} {fit(safe, CMD_W):<{CMD_W}} "
        f"{fit(selected, CMD_W):<{CMD_W}} "
        f"{fit(get(row, 'command_source'), SRC_W):<{SRC_W}} "
        f"{bool_cell(get(row, 'command_latched')):<2} "
        f"{bool_cell(get(row, 'command_policy_valid')):<2} "
        f"{bool_cell(get(row, 'auto_enable')):<4} "
        f"{bool_cell(get(row, 'avoid_active')):<5} "
        f"{bool_cell(get(row, 'takeover_active')):<4} "
        f"{bool_cell(get(row, 'override_active')):<3} "
        f"{bool_cell(get(row, 'override_blocked')):<3} "
        f"{bool_cell(get(row, 'operator_manual_authority')):<3}"
    )
    return out


def render_detector(line: str) -> Optional[str]:
    if "det=" not in line or "proc_ema=" not in line:
        return None
    row = tokens(line)
    proc = get(row, "proc_ema")
    if proc != "-" and not proc.endswith("ms"):
        proc = f"{proc}ms"
    parts = [
        f"{now_text()} DET  ",
        f"det={get(row, 'det')}",
        f"proc={proc}",
        f"frame={get(row, 'frames')}",
    ]
    if "conf" in row:
        parts.append(f"conf={row['conf']}")
    if "imgsz" in row:
        parts.append(f"imgsz={row['imgsz']}")
    return "  ".join(parts)


def render_camera(line: str) -> Optional[str]:
    if "cap_fps=" not in line or "pub_fps=" not in line:
        return None
    row = tokens(line)
    parts = [
        f"{now_text()} CAM  ",
        f"cap={get(row, 'cap_fps')}",
        f"pub={get(row, 'pub_fps')}",
    ]
    if "age" in row:
        parts.append(f"age={row['age']}")
    if "input" in row:
        parts.append(f"dev={row['input']}")
    elif "device" in row:
        parts.append(f"dev={row['device']}")
    elif "source" in row:
        parts.append(f"source={row['source']}")
    return "  ".join(parts)


def render_watchdog(line: str) -> Optional[str]:
    match = WATCHDOG_RE.search(line)
    if not match:
        return None
    return f"{now_text()} WATCH state={match.group(1).strip()}"


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

    row = tokens(line)
    reason = get(row, "reason")
    left = get(row, "L")
    right = get(row, "R")
    fs_age = get(row, "fs_age")
    if reason != "-" or left != "-" or right != "-" or fs_age != "-":
        return f"{now_text()} LIMIT reason={reason}  L={left}  R={right}  fs_age={fs_age}"

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


def unit_to_mb(value: float, unit: Optional[str]) -> float:
    unit = (unit or "MB").upper()
    if unit == "KB":
        return value / 1024.0
    if unit == "GB":
        return value * 1024.0
    return value


def latest_nonempty_line(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            if size <= 0:
                return ""
            handle.seek(max(0, size - 65536), os.SEEK_SET)
            data = handle.read().decode(errors="replace")
    except FileNotFoundError:
        return None
    except OSError:
        return None

    for line in reversed(data.splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def parse_tegrastats_line(line: str) -> Optional[Dict[str, float]]:
    metrics: Dict[str, float] = {}

    ram = RAM_RE.search(line)
    if ram:
        metrics["ram_used_gb"] = unit_to_mb(float(ram.group(1)), ram.group(3)) / 1024.0
        metrics["ram_total_gb"] = unit_to_mb(float(ram.group(2)), ram.group(3)) / 1024.0

    swap = SWAP_RE.search(line)
    if swap:
        metrics["swap_used_gb"] = unit_to_mb(float(swap.group(1)), swap.group(3)) / 1024.0
        metrics["swap_total_gb"] = unit_to_mb(float(swap.group(2)), swap.group(3)) / 1024.0

    cpu = CPU_RE.search(line)
    if cpu:
        loads = [float(value) for value in CPU_LOAD_RE.findall(cpu.group(1))]
        if loads:
            metrics["cpu_avg_pct"] = sum(loads) / len(loads)
            metrics["cpu_max_pct"] = max(loads)

    gpu = GPU_RE.search(line)
    if gpu:
        metrics["gpu_pct"] = float(gpu.group(1))

    tj_soc_max: Optional[float] = None
    for name, value in TEMP_RE.findall(line):
        temp = float(value)
        lname = name.lower()
        if lname in {"cpu", "tcpu", "mcpu", "bcpu"}:
            metrics["temp_cpu_c"] = max(metrics.get("temp_cpu_c", temp), temp)
        if "gpu" in lname:
            metrics["temp_gpu_c"] = max(metrics.get("temp_gpu_c", temp), temp)
        if "tj" in lname or "soc" in lname:
            tj_soc_max = temp if tj_soc_max is None else max(tj_soc_max, temp)
    if tj_soc_max is not None:
        metrics["temp_tj_soc_c"] = tj_soc_max

    power = VDD_IN_RE.search(line)
    if power:
        metrics["vdd_in_inst_w"] = float(power.group(1)) / 1000.0
        if power.group(2):
            metrics["vdd_in_avg_w"] = float(power.group(2)) / 1000.0

    return metrics or None


def fmt_pct(value: float) -> str:
    return f"{value:.1f}%"


def fmt_gb(value: float) -> str:
    return f"{value:.2f}GB"


def fmt_temp(value: float) -> str:
    return f"{value:.0f}C"


def fmt_power(value: float) -> str:
    return f"{value:.1f}W"


def render_sys_line(state: PrettyState) -> Optional[str]:
    path = os.environ.get("PHASE7_TEGRASTATS_RAW", "").strip()
    if not path:
        return None

    try:
        period = float(os.environ.get("PHASE7_SYS_PERIOD_S", str(DEFAULT_SYS_PERIOD_S)))
    except ValueError:
        period = DEFAULT_SYS_PERIOD_S
    period = max(1.0, period)

    now = time.monotonic()
    if now - state.last_sys_t < period:
        return None
    state.last_sys_t = now

    line = latest_nonempty_line(path)
    if line is None:
        if not state.warned_missing_tegra:
            state.warned_missing_tegra = True
            return f"{now_text()} WARN tegrastats raw file unavailable for SYS view"
        return None
    if not line:
        return None

    metrics = parse_tegrastats_line(line)
    if not metrics:
        if not state.warned_unparsed_tegra:
            state.warned_unparsed_tegra = True
            return f"{now_text()} WARN tegrastats raw line unparsable for SYS view"
        return None

    parts = [f"{now_text()} SYS  "]
    if "cpu_avg_pct" in metrics:
        parts.append(f"CPU={fmt_pct(metrics['cpu_avg_pct'])}")
    if "cpu_max_pct" in metrics:
        parts.append(f"max={fmt_pct(metrics['cpu_max_pct'])}")
    if "gpu_pct" in metrics:
        parts.append(f"GPU={fmt_pct(metrics['gpu_pct'])}")
    if "ram_used_gb" in metrics and "ram_total_gb" in metrics:
        parts.append(f"RAM={fmt_gb(metrics['ram_used_gb'])}/{fmt_gb(metrics['ram_total_gb'])}")
    if "swap_used_gb" in metrics and "swap_total_gb" in metrics:
        parts.append(
            f"SWAP={fmt_gb(metrics['swap_used_gb'])}/{fmt_gb(metrics['swap_total_gb'])}"
        )
    if "temp_cpu_c" in metrics:
        parts.append(f"Tcpu={fmt_temp(metrics['temp_cpu_c'])}")
    if "temp_gpu_c" in metrics:
        parts.append(f"Tgpu={fmt_temp(metrics['temp_gpu_c'])}")
    if "temp_tj_soc_c" in metrics:
        parts.append(f"Ttj_soc={fmt_temp(metrics['temp_tj_soc_c'])}")
    if "vdd_in_inst_w" in metrics:
        if "vdd_in_avg_w" in metrics:
            parts.append(
                f"Pin={fmt_power(metrics['vdd_in_inst_w'])}/{fmt_power(metrics['vdd_in_avg_w'])}"
            )
        else:
            parts.append(f"Pin={fmt_power(metrics['vdd_in_inst_w'])}")

    return "  ".join(parts)


def render_line(line: str, state: PrettyState) -> List[str]:
    try:
        if "phase7_sync " in line:
            return render_phase7_sync(line, state)
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
                return [rendered]
    except Exception as exc:
        return [f"{now_text()} WARN pretty_live parse_error={type(exc).__name__}"]
    return []


def main(lines: Iterable[str]) -> int:
    configure_stdout()
    state = PrettyState()
    print(sync_header(), flush=True)
    print(SYNC_LEGEND, flush=True)

    for line in lines:
        for rendered in render_line(line, state):
            print(rendered, flush=True)
        sys_line = render_sys_line(state)
        if sys_line:
            print(sys_line, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.stdin))
