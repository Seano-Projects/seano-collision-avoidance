#!/usr/bin/env python3
"""Check Phase 7 terminal logs for HUD/command/override sync mismatches."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import re
from typing import Dict, Iterable, List, Tuple


TOKEN_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=([^ \n]+)")
LOW_OK = {"", "HOLD_COURSE", "RC_OVERRIDE_RELEASE", "RELEASE"}
MEDIUM_OK = {"SLOW_DOWN", "TURN_LEFT_SLOW", "TURN_RIGHT_SLOW"}
HIGH_OK = {"STOP", "TURN_LEFT", "TURN_RIGHT"}


def parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def normalize_command(value: str) -> str:
    return str(value or "").strip().upper().replace("'", "").replace('"', "")


def parse_phase7_sync(lines: Iterable[str]) -> Iterable[Tuple[int, str, Dict[str, str]]]:
    for lineno, line in enumerate(lines, start=1):
        if "phase7_sync " not in line:
            continue
        yield lineno, line.rstrip("\n"), dict(TOKEN_RE.findall(line))


def check_record(lineno: int, row: Dict[str, str]) -> List[str]:
    findings: List[str] = []
    risk_class = str(row.get("risk_class", "UNKNOWN")).upper()
    cmd = normalize_command(row.get("command_selected", ""))
    avoid_active = parse_bool(row.get("avoid_active", "false"))
    auto_enable = parse_bool(row.get("auto_enable", "false"))
    takeover_active = parse_bool(row.get("takeover_active", "false"))
    override_active = parse_bool(row.get("override_active", "false"))
    manual_authority = parse_bool(row.get("operator_manual_authority", "false"))

    if risk_class == "LOW" and cmd not in LOW_OK:
        findings.append(f"{lineno}: LOW risk selected non-release command {cmd}")

    if risk_class == "MEDIUM" and cmd not in MEDIUM_OK:
        if not (manual_authority and cmd in LOW_OK):
            findings.append(f"{lineno}: MEDIUM risk selected non-medium command {cmd}")

    if risk_class == "HIGH" and cmd not in HIGH_OK:
        if not (manual_authority and cmd in LOW_OK):
            findings.append(f"{lineno}: HIGH risk selected weak/unknown command {cmd}")

    if takeover_active and not avoid_active:
        findings.append(f"{lineno}: takeover_active=true while avoid_active=false")

    if auto_enable and cmd in LOW_OK and not manual_authority:
        findings.append(f"{lineno}: command_mux AUTO selected while command_selected={cmd}")

    if override_active and not avoid_active:
        findings.append(f"{lineno}: override_active=true while HUD avoid_active=false")

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan terminal_log.txt for Phase 7 sync policy inconsistencies."
    )
    parser.add_argument("log", nargs="?", default="terminal_log.txt")
    parser.add_argument("--max-findings", type=int, default=50)
    args = parser.parse_args()

    path = Path(args.log)
    if not path.exists():
        print(f"ERROR: log file not found: {path}")
        return 2

    records = list(parse_phase7_sync(path.read_text(errors="replace").splitlines()))
    counts: Counter[str] = Counter()
    findings: List[str] = []

    for lineno, _line, row in records:
        counts["records"] += 1
        counts[f"risk_class:{str(row.get('risk_class', 'UNKNOWN')).upper()}"] += 1
        counts[f"command:{normalize_command(row.get('command_selected', ''))}"] += 1
        if parse_bool(row.get("avoid_active", "false")):
            counts["avoid_active:true"] += 1
        if parse_bool(row.get("auto_enable", "false")):
            counts["auto_enable:true"] += 1
        if parse_bool(row.get("takeover_active", "false")):
            counts["takeover_active:true"] += 1
        if parse_bool(row.get("override_active", "false")):
            counts["override_active:true"] += 1
        if parse_bool(row.get("override_blocked", "false")):
            counts["override_blocked:true"] += 1
        findings.extend(check_record(lineno, row))

    print(f"phase7_sync records: {counts['records']}")
    for key in sorted(k for k in counts if k != "records"):
        print(f"{key}: {counts[key]}")

    if not records:
        print("WARNING: no phase7_sync records found")
        return 1

    if findings:
        print("\nFindings:")
        for item in findings[: max(0, int(args.max_findings))]:
            print(f"- {item}")
        if len(findings) > args.max_findings:
            print(f"- ... {len(findings) - args.max_findings} more")
        return 1

    print("\nNo policy mismatches found in phase7_sync records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
