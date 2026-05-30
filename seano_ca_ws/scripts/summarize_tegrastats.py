#!/usr/bin/env python3
"""Summarize Jetson tegrastats output for Phase 7 evidence folders."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import statistics
from typing import Dict, Iterable, List, Optional


RAM_RE = re.compile(r"\bRAM\s+([0-9.]+)\/([0-9.]+)([KMG]B)?", re.IGNORECASE)
SWAP_RE = re.compile(r"\bSWAP\s+([0-9.]+)\/([0-9.]+)([KMG]B)?", re.IGNORECASE)
CPU_RE = re.compile(r"\bCPU\s+\[([^\]]+)\]", re.IGNORECASE)
CPU_LOAD_RE = re.compile(r"([0-9.]+)%")
GPU_RE = re.compile(r"\b(?:GR3D_FREQ|GR3D|GPU)\s+([0-9.]+)%", re.IGNORECASE)
TEMP_RE = re.compile(r"\b([A-Za-z0-9_]+)@([0-9.]+)C")
POWER_RE = re.compile(r"\b([A-Za-z0-9_]+)\s+([0-9.]+)mW(?:\/([0-9.]+)mW)?")


def unit_to_mb(value: float, unit: Optional[str]) -> float:
    unit = (unit or "MB").upper()
    if unit == "KB":
        return value / 1024.0
    if unit == "GB":
        return value * 1024.0
    return value


def add_metric(metrics: Dict[str, List[float]], key: str, value: float) -> None:
    metrics.setdefault(key, []).append(float(value))


def fmt_stats(values: List[float], suffix: str = "") -> str:
    if not values:
        return "not parsed"
    return (
        f"min={min(values):.1f}{suffix} "
        f"max={max(values):.1f}{suffix} "
        f"avg={statistics.fmean(values):.1f}{suffix}"
    )


def parse_lines(lines: Iterable[str]) -> tuple[int, Dict[str, List[float]], Dict[str, float]]:
    metrics: Dict[str, List[float]] = {}
    temp_max: Dict[str, float] = {}
    samples = 0

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        samples += 1

        ram = RAM_RE.search(line)
        if ram:
            add_metric(metrics, "ram_used_mb", unit_to_mb(float(ram.group(1)), ram.group(3)))
            add_metric(metrics, "ram_total_mb", unit_to_mb(float(ram.group(2)), ram.group(3)))

        swap = SWAP_RE.search(line)
        if swap:
            add_metric(metrics, "swap_used_mb", unit_to_mb(float(swap.group(1)), swap.group(3)))
            add_metric(metrics, "swap_total_mb", unit_to_mb(float(swap.group(2)), swap.group(3)))

        cpu = CPU_RE.search(line)
        if cpu:
            loads = [float(value) for value in CPU_LOAD_RE.findall(cpu.group(1))]
            if loads:
                add_metric(metrics, "cpu_avg_load_pct", statistics.fmean(loads))
                add_metric(metrics, "cpu_max_core_load_pct", max(loads))

        gpu = GPU_RE.search(line)
        if gpu:
            add_metric(metrics, "gr3d_gpu_load_pct", float(gpu.group(1)))

        for name, value in TEMP_RE.findall(line):
            temp_max[name] = max(temp_max.get(name, float("-inf")), float(value))

        for name, instant, average in POWER_RE.findall(line):
            add_metric(metrics, f"power_{name}_instant_mw", float(instant))
            if average:
                add_metric(metrics, f"power_{name}_average_mw", float(average))

    return samples, metrics, temp_max


def print_summary(path: Path, samples: int, metrics: Dict[str, List[float]], temp_max: Dict[str, float]) -> None:
    print("Tegrastats summary")
    print(f"source: {path}")
    print(f"samples: {samples}")
    print()

    if samples == 0:
        print("No tegrastats samples found.")
        return

    parsed_any = bool(metrics or temp_max)

    print(f"RAM used: {fmt_stats(metrics.get('ram_used_mb', []), ' MB')}")
    print(f"SWAP used: {fmt_stats(metrics.get('swap_used_mb', []), ' MB')}")
    print(f"CPU avg load: {fmt_stats(metrics.get('cpu_avg_load_pct', []), '%')}")
    print(f"CPU max core load: {fmt_stats(metrics.get('cpu_max_core_load_pct', []), '%')}")
    print(f"GR3D/GPU load: {fmt_stats(metrics.get('gr3d_gpu_load_pct', []), '%')}")

    if temp_max:
        print("Temperature max:")
        for name in sorted(temp_max):
            print(f"  {name}: {temp_max[name]:.1f} C")
    else:
        print("Temperature max: not parsed")

    power_keys = sorted(key for key in metrics if key.startswith("power_"))
    if power_keys:
        print("Power:")
        for key in power_keys:
            label = key.removeprefix("power_").replace("_", " ")
            print(f"  {label}: {fmt_stats(metrics[key], ' mW')}")
    else:
        print("Power: not parsed")

    missing = []
    for label, key in (
        ("RAM", "ram_used_mb"),
        ("SWAP", "swap_used_mb"),
        ("CPU", "cpu_avg_load_pct"),
        ("GR3D/GPU", "gr3d_gpu_load_pct"),
    ):
        if key not in metrics:
            missing.append(label)
    if not temp_max:
        missing.append("temperature")
    if not power_keys:
        missing.append("power")

    if missing:
        print()
        print("Metrics not parsed from this tegrastats format: " + ", ".join(missing))
        print("Raw tegrastats remains preserved in tegrastats_raw.txt.")
    elif not parsed_any:
        print()
        print("No parseable metrics found; raw tegrastats remains preserved.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize Jetson tegrastats raw output.")
    parser.add_argument("tegrastats_raw", type=Path)
    args = parser.parse_args()

    if not args.tegrastats_raw.exists():
        print(f"ERROR: tegrastats file not found: {args.tegrastats_raw}")
        return 2

    lines = args.tegrastats_raw.read_text(errors="replace").splitlines()
    samples, metrics, temp_max = parse_lines(lines)
    print_summary(args.tegrastats_raw, samples, metrics, temp_max)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
