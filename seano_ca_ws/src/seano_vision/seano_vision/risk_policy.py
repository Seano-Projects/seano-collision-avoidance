"""Shared Phase 7 risk-band policy.

These constants define the operator-facing risk bands. Nodes may still expose
ROS parameters for field tuning, but defaults should stay aligned here.
"""

LOW_RISK_MAX = 0.30
HIGH_RISK_MIN = 0.60
EMERGENCY_STOP_RISK = 0.92
RELEASE_RISK_MAX = 0.25

CMD_HOLD = "HOLD_COURSE"
CMD_SLOW = "SLOW_DOWN"
CMD_TURN_LEFT_SLOW = "TURN_LEFT_SLOW"
CMD_TURN_RIGHT_SLOW = "TURN_RIGHT_SLOW"
CMD_STOP = "STOP"
CMD_TURN_LEFT = "TURN_LEFT"
CMD_TURN_RIGHT = "TURN_RIGHT"

LOW_COMMANDS = {CMD_HOLD}
MEDIUM_COMMANDS = {CMD_SLOW, CMD_TURN_LEFT_SLOW, CMD_TURN_RIGHT_SLOW}
HIGH_COMMANDS = {CMD_STOP, CMD_TURN_LEFT, CMD_TURN_RIGHT}
AVOIDANCE_COMMANDS = MEDIUM_COMMANDS | HIGH_COMMANDS

EMERGENCY_SOURCES = {"EMERGENCY", "EMERGENCY_VTTC"}
FAILSAFE_SOURCES = {"FAILSAFE", "INVALID_DATA"}
LOW_LATCH_SOURCES = {"RECOVERY"}
BYPASS_SOURCES = EMERGENCY_SOURCES | FAILSAFE_SOURCES


def classify_risk(risk: float) -> str:
    """Return LOW/MEDIUM/HIGH using the Phase 7 operator policy."""
    try:
        value = max(0.0, min(1.0, float(risk)))
    except Exception:
        value = 0.0

    if value < LOW_RISK_MAX:
        return "LOW"
    if value < HIGH_RISK_MIN:
        return "MEDIUM"
    return "HIGH"


def normalize_command(command: str) -> str:
    return str(command or "").strip().upper()


def normalize_source(source: str) -> str:
    text = str(source or "").strip().upper()
    text = text.replace("-", "_").replace(" ", "_")
    return text


def source_allows_policy_bypass(command_source: str) -> bool:
    source = normalize_source(command_source)
    return source in BYPASS_SOURCES


def source_allows_low_latch(command_source: str, command_latched: bool = False) -> bool:
    source = normalize_source(command_source)
    return source in LOW_LATCH_SOURCES


def command_is_avoidance(command: str) -> bool:
    return normalize_command(command) in AVOIDANCE_COMMANDS


def command_is_high_severity(command: str) -> bool:
    return normalize_command(command) in HIGH_COMMANDS


def command_allowed_for_risk_class(
    command: str,
    risk_class: str,
    command_source: str = "POLICY",
    command_latched: bool = False,
    medium_hold_allowed: bool = False,
) -> bool:
    cmd = normalize_command(command)
    risk_band = str(risk_class or "UNKNOWN").strip().upper()

    if source_allows_policy_bypass(command_source):
        return True

    if risk_band == "LOW":
        if cmd in LOW_COMMANDS:
            return True
        return (
            source_allows_low_latch(command_source, command_latched)
            and cmd in AVOIDANCE_COMMANDS
        )

    if risk_band == "MEDIUM":
        return cmd in MEDIUM_COMMANDS or (bool(medium_hold_allowed) and cmd in LOW_COMMANDS)

    if risk_band == "HIGH":
        return cmd in HIGH_COMMANDS

    return cmd in LOW_COMMANDS


def command_allowed_for_risk(
    command: str,
    risk: float,
    command_source: str = "POLICY",
    command_latched: bool = False,
    medium_hold_allowed: bool = False,
) -> bool:
    return command_allowed_for_risk_class(
        command=command,
        risk_class=classify_risk(risk),
        command_source=command_source,
        command_latched=command_latched,
        medium_hold_allowed=medium_hold_allowed,
    )


def clamp_command_for_risk(
    command: str,
    risk: float,
    command_source: str = "POLICY",
    command_latched: bool = False,
    preferred_command: str = "",
    medium_hold_allowed: bool = False,
) -> tuple[str, bool, str]:
    """Return command clamped to the Phase 7 operator risk-band policy.

    The bool is true when the input command already satisfied the policy for
    the supplied risk/source/latch state.
    """
    cmd = normalize_command(command) or CMD_HOLD
    preferred = normalize_command(preferred_command)
    risk_class = classify_risk(risk)

    if command_allowed_for_risk_class(
        cmd,
        risk_class,
        command_source,
        command_latched,
        medium_hold_allowed=medium_hold_allowed,
    ):
        return cmd, True, risk_class

    if source_allows_policy_bypass(command_source):
        return cmd, True, risk_class

    if risk_class == "LOW":
        return CMD_HOLD, False, risk_class

    if risk_class == "MEDIUM":
        if cmd == CMD_TURN_LEFT:
            return CMD_TURN_LEFT_SLOW, False, risk_class
        if cmd == CMD_TURN_RIGHT:
            return CMD_TURN_RIGHT_SLOW, False, risk_class
        return CMD_SLOW, False, risk_class

    if risk_class == "HIGH":
        if preferred in HIGH_COMMANDS:
            return preferred, False, risk_class
        if cmd == CMD_TURN_LEFT_SLOW:
            return CMD_TURN_LEFT, False, risk_class
        if cmd == CMD_TURN_RIGHT_SLOW:
            return CMD_TURN_RIGHT, False, risk_class
        return CMD_STOP, False, risk_class

    return CMD_HOLD, False, risk_class
