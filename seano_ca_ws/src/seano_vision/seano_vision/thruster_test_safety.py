"""Pure safety policy for the guarded shared-MQTT thruster test.

This module has no ROS, MQTT, MAVROS, or hardware side effects.  Keeping the
state machines pure lets the dangerous path be exercised with a fake transport
before an operator ever enables the hardware-test runtime.
"""

from __future__ import annotations

import json
import hashlib
import math
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from .risk_policy import normalize_command_details


SOURCE_ID = "collision_avoidance_test"
SHARED_TOPIC = "seano/USV-001/thruster"
MOTION_COMMANDS = {
    "SLOW_DOWN", "TURN_LEFT_SLOW", "TURN_RIGHT_SLOW", "TURN_LEFT", "TURN_RIGHT"
}


def clamp(value: float, low: float, high: float) -> float:
    return max(float(low), min(float(high), float(value)))


@dataclass(frozen=True)
class TestLimits:
    mapping_profile: str = "LEGACY_CONSERVATIVE"
    maximum_throttle_percent: float = 10.0
    maximum_allowed_throttle_percent: float = 10.0
    cruise_reference_throttle_percent: float = 20.0
    slow_factor: float = 0.5
    slow_throttle_percent: float = 10.0
    minimum_effective_throttle_percent: float = 10.0
    turn_throttle_percent: float = 10.0
    maximum_steering_percent: float = 15.0
    maximum_allowed_steering_percent: float = 15.0
    steering_channel_index: int = 0
    throttle_channel_index: int = 2
    pwm_min: int = 1000
    neutral_throttle_pwm: int = 1500
    pwm_max: int = 2000
    command_timeout_s: float = 0.30
    heartbeat_timeout_s: float = 0.50
    maximum_motion_duration_s: float = 2.0
    reverse_allowed: bool = False
    mqtt_qos: int = 1
    mqtt_retain: bool = False

    def validate_first_test(self) -> tuple[bool, str]:
        values = (
            self.maximum_throttle_percent,
            self.maximum_allowed_throttle_percent,
            self.cruise_reference_throttle_percent,
            self.slow_factor,
            self.slow_throttle_percent,
            self.minimum_effective_throttle_percent,
            self.turn_throttle_percent,
            self.maximum_steering_percent,
            self.maximum_allowed_steering_percent,
            self.command_timeout_s, self.heartbeat_timeout_s,
            self.maximum_motion_duration_s,
        )
        if not all(math.isfinite(float(v)) for v in values):
            return False, "NON_FINITE_LIMIT"
        positive_values = (
            self.maximum_throttle_percent,
            self.maximum_allowed_throttle_percent,
            self.cruise_reference_throttle_percent,
            self.slow_factor,
            self.slow_throttle_percent,
            self.minimum_effective_throttle_percent,
            self.maximum_steering_percent,
            self.maximum_allowed_steering_percent,
            self.command_timeout_s,
            self.heartbeat_timeout_s,
            self.maximum_motion_duration_s,
        )
        if not all(float(v) > 0.0 for v in positive_values):
            return False, "NON_FINITE_OR_NON_POSITIVE_LIMIT"
        if float(self.turn_throttle_percent) < 0.0:
            return False, "NEGATIVE_TURN_THROTTLE"
        profile = str(self.mapping_profile or "").strip().upper()
        if profile not in {"LEGACY_CONSERVATIVE", "SEAPORTAL_ACTUAL"}:
            return False, "UNKNOWN_THRUSTER_MAPPING_PROFILE"
        if (
            int(self.steering_channel_index) < 0
            or int(self.throttle_channel_index) < 0
            or int(self.steering_channel_index)
            == int(self.throttle_channel_index)
        ):
            return False, "THRUSTER_CHANNEL_CONFIG_INVALID"
        if not int(self.pwm_min) < int(self.neutral_throttle_pwm) < int(self.pwm_max):
            return False, "THRUSTER_PWM_CONFIG_INVALID"
        if (
            self.maximum_throttle_percent
            > self.maximum_allowed_throttle_percent
        ):
            return False, "THROTTLE_LIMIT_EXCEEDS_FIRST_TEST_MAXIMUM"
        if not 0.0 < self.slow_factor < 1.0:
            return False, "SLOW_FACTOR_OUT_OF_RANGE"
        slow_target = max(
            self.minimum_effective_throttle_percent,
            self.cruise_reference_throttle_percent * self.slow_factor,
        )
        if slow_target > self.maximum_throttle_percent:
            return False, "SLOW_THROTTLE_BELOW_EFFECTIVE_THRESHOLD"
        if not (
            self.minimum_effective_throttle_percent
            <= self.slow_throttle_percent
            < self.cruise_reference_throttle_percent
            and self.slow_throttle_percent
            <= self.maximum_throttle_percent
        ):
            return False, "SLOW_THROTTLE_CALIBRATION_INVALID"
        if profile == "SEAPORTAL_ACTUAL":
            seaportal_values = (
                (self.maximum_throttle_percent, 58.0),
                (self.slow_throttle_percent, 58.0),
                (self.minimum_effective_throttle_percent, 58.0),
                (self.turn_throttle_percent, 0.0),
                (self.maximum_steering_percent, 100.0),
                (self.cruise_reference_throttle_percent, 100.0),
                (self.slow_factor, 0.58),
            )
            if (
                any(abs(float(actual) - expected) > 1e-6
                    for actual, expected in seaportal_values)
                or int(self.steering_channel_index) != 0
                or int(self.throttle_channel_index) != 2
                or int(self.pwm_min) != 1000
                or int(self.neutral_throttle_pwm) != 1500
                or int(self.pwm_max) != 2000
            ):
                return False, "SEAPORTAL_MAPPING_CONFIG_INVALID"
        elif not (
            self.minimum_effective_throttle_percent
            <= self.turn_throttle_percent
            <= self.maximum_throttle_percent
        ):
            return False, "TURN_THROTTLE_CALIBRATION_INVALID"
        if abs(self.slow_throttle_percent - slow_target) > 1e-6:
            return False, "SLOW_THROTTLE_CONFIG_MISMATCH"
        if (
            self.maximum_steering_percent
            > self.maximum_allowed_steering_percent
        ):
            return False, "STEERING_LIMIT_EXCEEDS_FIRST_TEST_MAXIMUM"
        if self.maximum_motion_duration_s > 2.0:
            return False, "MOTION_DURATION_EXCEEDS_FIRST_TEST_MAXIMUM"
        if self.mqtt_qos != 1:
            return False, "MQTT_QOS_MUST_BE_ONE"
        if self.mqtt_retain:
            return False, "MQTT_RETAIN_MUST_BE_FALSE"
        if self.reverse_allowed:
            return False, "REVERSE_MUST_BE_DISABLED"
        return True, "VALID"

    @property
    def effective_slow_throttle_percent(self) -> float:
        return clamp(
            max(
                self.minimum_effective_throttle_percent,
                self.cruise_reference_throttle_percent * self.slow_factor,
            ),
            0.0,
            self.maximum_throttle_percent,
        )


@dataclass(frozen=True)
class StaticGates:
    hardware_test_enabled: bool = False
    mqtt_publish_enabled: bool = False
    operator_confirmed: bool = False
    shared_mqtt_test_confirmed: bool = False
    tether_confirmed: bool = False
    emergency_stop_confirmed: bool = False
    exclusive_test_window_confirmed: bool = False
    foreign_command_monitor_enabled: bool = True

    def closed_reasons(self) -> list[str]:
        checks = (
            (self.hardware_test_enabled, "HARDWARE_TEST_DISABLED"),
            (self.mqtt_publish_enabled, "MQTT_PUBLISH_DISABLED"),
            (self.operator_confirmed, "OPERATOR_NOT_CONFIRMED"),
            (self.shared_mqtt_test_confirmed, "SHARED_MQTT_NOT_CONFIRMED"),
            (self.tether_confirmed, "TETHER_NOT_CONFIRMED"),
            (self.emergency_stop_confirmed, "EMERGENCY_STOP_NOT_CONFIRMED"),
            (self.exclusive_test_window_confirmed, "EXCLUSIVE_WINDOW_NOT_CONFIRMED"),
            (self.foreign_command_monitor_enabled, "FOREIGN_MONITOR_DISABLED"),
        )
        return [reason for value, reason in checks if not value]


@dataclass
class GuardianInputs:
    now: float
    started_at: float
    adapter_heartbeat_at: float = 0.0
    command_at: float = 0.0
    safe_command_at: float = 0.0
    command: str = "STALE"
    failsafe: bool = True
    lost_perception: bool = True
    mqtt_connected: bool = False
    foreign_command: bool = False
    foreign_command_reason: str = ""
    operator_enable: bool = False
    throttle_percent: float = 0.0
    steering_percent: float = 0.0
    fcu_connected: bool = False
    fcu_armed: bool = False
    fcu_mode: str = ""
    required_fcu_mode: str = "MANUAL"
    rc_publisher_count: int = 0
    rc_publisher_name: str = ""
    rc_subscriber_present: bool = False
    web_video_available: bool = True
    hud_heartbeat_fresh: bool = True
    guardian_heartbeat_fresh: bool = True


@dataclass(frozen=True)
class GuardianDecision:
    motion_allowed: bool
    status: str
    abort_reason: str = ""
    blocked_reason: str = ""
    actuator_path_ready: bool = False


class GuardianCore:
    """Latched fail-closed guardian decision engine."""

    def __init__(self, gates: StaticGates, limits: TestLimits, observation_window_s: float = 1.0,
                 startup_grace_s: float = 5.0):
        self.gates = gates
        self.limits = limits
        self.observation_window_s = max(0.0, float(observation_window_s))
        self.startup_grace_s = max(self.observation_window_s, float(startup_grace_s))
        self.aborted = False
        self.abort_reason = ""
        self.motion_started_at = 0.0
        self.armed_seen = False
        self.ready_seen = False
        self.state = "STARTING"

    def _abort(self, reason: str, foreign: bool = False) -> GuardianDecision:
        self.aborted = True
        self.abort_reason = str(reason)
        self.state = "ABORTED"
        return GuardianDecision(
            motion_allowed=False,
            status="ABORTED_FOREIGN_COMMAND" if foreign else "ABORTED",
            abort_reason=self.abort_reason,
        )

    def _wait(self, status: str, reason: str) -> GuardianDecision:
        self.state = status
        return GuardianDecision(
            motion_allowed=False,
            status=status,
            blocked_reason=reason,
            actuator_path_ready=False,
        )

    def _runtime_fault_or_wait(
        self, reason: str, status: str = "WAITING_FOR_CA_READY"
    ) -> GuardianDecision:
        if self.motion_started_at or self.ready_seen:
            return self._abort(reason)
        return self._wait(status, reason)

    def evaluate(self, data: GuardianInputs) -> GuardianDecision:
        if self.aborted:
            return GuardianDecision(
                motion_allowed=False,
                status="ABORTED_FOREIGN_COMMAND" if "FOREIGN" in self.abort_reason else "ABORTED",
                abort_reason=self.abort_reason,
            )
        valid, limit_reason = self.limits.validate_first_test()
        if not valid:
            return self._abort(limit_reason)
        closed = self.gates.closed_reasons()
        if closed:
            return self._wait("PREVIEW_ONLY", ";".join(closed))
        if data.foreign_command:
            reason = str(data.foreign_command_reason or "").strip()
            if reason not in {
                "FOREIGN_ACTIVE_COMMAND",
                "FOREIGN_ACTIVE_COMMAND_DURING_MOTION",
                "FOREIGN_UNKNOWN_SCHEMA",
                "FOREIGN_RETAINED_MESSAGE",
            }:
                reason = "FOREIGN_UNKNOWN_SCHEMA"
            return self._abort(reason, foreign=True)
        if not data.operator_enable:
            if self.motion_started_at:
                return self._abort("OPERATOR_ENABLE_RELEASED")
            return self._wait("PREVIEW_ONLY", "OPERATOR_ENABLE_FALSE")
        if data.now - data.started_at < self.startup_grace_s:
            return self._wait("STARTING", "STARTUP_GRACE")
        if not data.fcu_connected:
            return self._runtime_fault_or_wait("FCU_STATE_NOT_READY")
        if (
            data.fcu_armed
            and not self.armed_seen
            and self.state != "WAITING_FOR_OPERATOR_ARM"
        ):
            return self._abort("BLOCKED_UNEXPECTED_ARM")
        if data.rc_publisher_count != 1 or data.rc_publisher_name != "/usv/thruster":
            return self._abort("RC_OVERRIDE_PUBLISHER_CHANGED")
        if not data.rc_subscriber_present:
            return self._abort("MAVROS_RC_SUBSCRIBER_MISSING")
        if not data.web_video_available:
            return self._runtime_fault_or_wait("HUD_WEB_VIDEO_UNAVAILABLE")
        if not data.hud_heartbeat_fresh:
            return self._runtime_fault_or_wait("HUD_HEARTBEAT_STALE")
        if not data.guardian_heartbeat_fresh:
            return self._runtime_fault_or_wait("GUARDIAN_HEARTBEAT_STALE")
        if not data.mqtt_connected:
            return self._runtime_fault_or_wait("MQTT_DISCONNECTED")
        if data.now - data.started_at < self.observation_window_s:
            return self._wait("STARTING", "FOREIGN_OBSERVATION_WINDOW")
        if data.adapter_heartbeat_at <= 0.0 or data.now - data.adapter_heartbeat_at > self.limits.heartbeat_timeout_s:
            return self._runtime_fault_or_wait("ADAPTER_HEARTBEAT_STALE")
        if data.command_at <= 0.0 or data.now - data.command_at > self.limits.command_timeout_s:
            return self._runtime_fault_or_wait("COMMAND_STALE")
        if data.safe_command_at <= 0.0 or data.now - data.safe_command_at > self.limits.command_timeout_s:
            return self._runtime_fault_or_wait("SAFE_COMMAND_STALE")
        if data.failsafe:
            return self._runtime_fault_or_wait("FAILSAFE_ACTIVE")
        if data.lost_perception:
            return self._runtime_fault_or_wait("LOST_PERCEPTION")
        required_mode = str(data.required_fcu_mode).strip().upper()
        mode_ready = bool(required_mode) and data.fcu_mode.strip().upper() == required_mode
        if not mode_ready:
            if self.motion_started_at or self.ready_seen or self.armed_seen:
                return self._abort("FCU_MODE_CHANGED")
            return self._wait(
                "WAITING_FOR_OPERATOR_MODE",
                f"REQUIRED_FCU_MODE_{required_mode or 'UNSET'}",
            )
        if data.fcu_armed:
            if not self.armed_seen and self.state != "WAITING_FOR_OPERATOR_ARM":
                return self._abort("BLOCKED_UNEXPECTED_ARM")
            self.armed_seen = True
        elif self.armed_seen or self.motion_started_at or self.ready_seen:
            return self._abort("FCU_DISARMED_AFTER_READY")
        else:
            return self._wait("WAITING_FOR_OPERATOR_ARM", "FCU_DISARMED")
        if not all(math.isfinite(v) for v in (data.throttle_percent, data.steering_percent)):
            return self._abort("NON_FINITE_OUTPUT")
        if not self.limits.reverse_allowed and data.throttle_percent < 0.0:
            return self._abort("REVERSE_DETECTED")
        if data.throttle_percent > self.limits.maximum_throttle_percent + 1e-6:
            return self._abort("THROTTLE_LIMIT_EXCEEDED")
        if abs(data.steering_percent) > self.limits.maximum_steering_percent + 1e-6:
            return self._abort("STEERING_LIMIT_EXCEEDED")
        command, known, _ = normalize_command_details(data.command)
        if not known or command == "STALE":
            return self._runtime_fault_or_wait("SAFE_COMMAND_INVALID")
        moving = command in MOTION_COMMANDS and data.throttle_percent > 0.0
        if moving:
            self.ready_seen = True
            if self.motion_started_at <= 0.0:
                self.motion_started_at = data.now
            elif data.now - self.motion_started_at > self.limits.maximum_motion_duration_s:
                return self._abort("MAXIMUM_MOTION_DURATION_EXCEEDED")
            return GuardianDecision(
                motion_allowed=True,
                status="MOTION_ACTIVE",
                actuator_path_ready=True,
            )
        self.motion_started_at = 0.0
        self.ready_seen = True
        return GuardianDecision(
            motion_allowed=False,
            status="READY_FOR_OBSTACLE_TEST",
            blocked_reason=(
                "STOP_NEUTRAL_ONLY"
                if command == "STOP"
                else "WAITING_VALID_HAZARD_COMMAND"
            ),
            actuator_path_ready=True,
        )


@dataclass(frozen=True)
class MappedThrusterCommand:
    command: str
    throttle_percent: float
    steering_percent: float
    requested_steering_pwm: int | None
    requested_throttle_pwm: int | None
    override_active: bool
    valid: bool
    reason: str


def canonical_thruster_mapping(
    command: str,
    limits: TestLimits,
    *,
    source_left: float | None = None,
    source_right: float | None = None,
) -> MappedThrusterCommand:
    """Canonical percent/PWM mapping shared by adapter, HUD, logs, and tests."""
    if source_left is not None or source_right is not None:
        try:
            left = float(source_left)
            right = float(source_right)
        except (TypeError, ValueError):
            left = right = math.nan
        if not all(math.isfinite(value) for value in (left, right)):
            command = "STOP"
            source_reason = "NON_FINITE_OUTPUT"
        elif not limits.reverse_allowed and (left + right) / 2.0 < -1e-9:
            command = "STOP"
            source_reason = "REVERSE_DETECTED"
        else:
            source_reason = ""
    else:
        source_reason = ""
    cmd, known, _ = normalize_command_details(command)
    if not known:
        cmd = "STOP"
        valid, reason = False, "UNKNOWN_COMMAND"
    else:
        valid, reason = True, "VALID"
    if source_reason:
        valid, reason = False, source_reason
    seaportal_actual = (
        str(limits.mapping_profile or "").strip().upper()
        == "SEAPORTAL_ACTUAL"
    )
    if cmd == "HOLD_COURSE":
        return MappedThrusterCommand(
            cmd, 0.0, 0.0, None, None, False, valid, reason
        )
    if cmd == "STOP":
        throttle, steering = 0.0, 0.0
    elif cmd == "SLOW_DOWN":
        throttle = limits.effective_slow_throttle_percent
        steering = 0.0
    elif cmd == "TURN_RIGHT_SLOW":
        throttle = limits.effective_slow_throttle_percent
        steering = (
            -limits.maximum_steering_percent
            if seaportal_actual
            else limits.maximum_steering_percent
        )
    elif cmd == "TURN_LEFT_SLOW":
        throttle = limits.effective_slow_throttle_percent
        steering = (
            limits.maximum_steering_percent
            if seaportal_actual
            else -limits.maximum_steering_percent
        )
    elif cmd == "TURN_RIGHT":
        throttle = limits.turn_throttle_percent
        steering = (
            -limits.maximum_steering_percent
            if seaportal_actual
            else limits.maximum_steering_percent
        )
    elif cmd == "TURN_LEFT":
        throttle = limits.turn_throttle_percent
        steering = (
            limits.maximum_steering_percent
            if seaportal_actual
            else -limits.maximum_steering_percent
        )
    else:
        cmd, throttle, steering = "STOP", 0.0, 0.0
        valid, reason = False, "UNKNOWN_COMMAND"
    if steering >= 0.0:
        steering_pwm = limits.neutral_throttle_pwm - round(
            (steering / 100.0)
            * (limits.neutral_throttle_pwm - limits.pwm_min)
        )
    else:
        steering_pwm = limits.neutral_throttle_pwm + round(
            (abs(steering) / 100.0)
            * (limits.pwm_max - limits.neutral_throttle_pwm)
        )
    throttle_pwm = limits.neutral_throttle_pwm + round(
        (throttle / 100.0)
        * (limits.pwm_max - limits.neutral_throttle_pwm)
    )
    return MappedThrusterCommand(
        cmd,
        float(throttle),
        float(steering),
        int(steering_pwm),
        int(throttle_pwm),
        True,
        valid,
        reason,
    )


def command_to_test_output(command: str, left: float, right: float, limits: TestLimits) -> tuple[float, float, str]:
    """Backward-compatible wrapper around the canonical command mapping."""
    mapped = canonical_thruster_mapping(
        command,
        limits,
        source_left=left,
        source_right=right,
    )
    return (
        mapped.throttle_percent,
        mapped.steering_percent,
        mapped.reason,
    )


@dataclass(frozen=True)
class PublishAction:
    kind: str
    payload: dict[str, Any]
    qos: int = 1
    retain: bool = False


OWN_MQTT_ECHO = "OWN_MQTT_ECHO"
BENIGN_RELEASE = "BENIGN_RELEASE"
BENIGN_NEUTRAL = "BENIGN_NEUTRAL"
ACTIVE_FOREIGN_COMMAND = "ACTIVE_FOREIGN_COMMAND"
UNKNOWN_SCHEMA = "UNKNOWN_SCHEMA"
ZERO_EPSILON = 1e-9


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _optional_sequence(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_identifier(value: Any) -> str | None:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    text = " ".join(str(value).split())
    return text[:128] if text else None


@dataclass
class PendingOwnMessage:
    token: int
    source: str
    session_id: str
    sequence: int
    payload_hash: str
    kind: str
    payload_timestamp: float
    registered_at: float
    expires_at: float
    mid: int | None = None
    echo_seen: bool = False
    acknowledged: bool = False


@dataclass(frozen=True)
class OwnMessageMatch:
    matched_pending_own: bool = False
    matched_completed_own: bool = False
    pending_age_s: float | None = None
    token: int | None = None
    kind: str = ""

    @property
    def matched(self) -> bool:
        return self.matched_pending_own or self.matched_completed_own


class OwnMessageRegistry:
    """Bounded, thread-safe correlation for MQTT publishes and local echoes."""

    def __init__(
        self,
        *,
        pending_ttl_s: float = 5.0,
        completed_grace_s: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.pending_ttl_s = max(0.01, float(pending_ttl_s))
        self.completed_grace_s = max(0.01, float(completed_grace_s))
        self.clock = clock
        self._lock = threading.RLock()
        self._next_token = 0
        self._pending: dict[int, PendingOwnMessage] = {}
        self._completed: dict[int, PendingOwnMessage] = {}

    def _prune_locked(self, now: float) -> None:
        for records in (self._pending, self._completed):
            expired = [
                token
                for token, entry in records.items()
                if now > entry.expires_at
            ]
            for token in expired:
                records.pop(token, None)

    def register(
        self,
        action: PublishAction,
        payload_hash: str,
    ) -> int:
        now = self.clock()
        payload = action.payload
        session_id = str(payload.get("session_id") or "")
        sequence = _optional_sequence(payload.get("sequence"))
        if not session_id or sequence is None:
            raise ValueError("OWN_MESSAGE_IDENTITY_REQUIRED")
        with self._lock:
            self._prune_locked(now)
            self._next_token += 1
            token = self._next_token
            self._pending[token] = PendingOwnMessage(
                token=token,
                source=str(payload.get("source") or ""),
                session_id=session_id,
                sequence=sequence,
                payload_hash=payload_hash,
                kind=str(action.kind),
                payload_timestamp=float(payload.get("timestamp", 0.0)),
                registered_at=now,
                expires_at=now + self.pending_ttl_s,
            )
            return token

    def bind_mid(self, token: int, mid: int) -> None:
        with self._lock:
            entry = self._pending.get(token) or self._completed.get(token)
            if entry is not None:
                entry.mid = int(mid)

    def discard(self, token: int) -> None:
        with self._lock:
            self._pending.pop(token, None)
            self._completed.pop(token, None)

    @staticmethod
    def _matches(
        entry: PendingOwnMessage,
        payload: Mapping[str, Any],
        payload_hash: str,
    ) -> bool:
        session_id = str(payload.get("session_id") or "")
        sequence = _optional_sequence(payload.get("sequence"))
        source = str(payload.get("source") or "")
        source_session_sequence = (
            source == SOURCE_ID
            and session_id == entry.session_id
            and sequence == entry.sequence
        )
        session_sequence = (
            session_id == entry.session_id and sequence == entry.sequence
        )
        hash_match = payload_hash == entry.payload_hash
        return source_session_sequence or session_sequence or hash_match

    def match(
        self,
        payload: Mapping[str, Any],
        payload_hash: str,
        *,
        retained: bool,
    ) -> OwnMessageMatch:
        if retained:
            return OwnMessageMatch()
        now = self.clock()
        with self._lock:
            self._prune_locked(now)
            for token, entry in tuple(self._pending.items()):
                if not self._matches(entry, payload, payload_hash):
                    continue
                entry.echo_seen = True
                entry.expires_at = now + self.completed_grace_s
                self._pending.pop(token, None)
                self._completed[token] = entry
                return OwnMessageMatch(
                    matched_pending_own=True,
                    pending_age_s=max(0.0, now - entry.registered_at),
                    token=token,
                    kind=entry.kind,
                )
            for token, entry in self._completed.items():
                if self._matches(entry, payload, payload_hash):
                    return OwnMessageMatch(
                        matched_completed_own=True,
                        pending_age_s=max(0.0, now - entry.registered_at),
                        token=token,
                        kind=entry.kind,
                    )
        return OwnMessageMatch()

    def acknowledge(self, mid: int) -> OwnMessageMatch:
        now = self.clock()
        with self._lock:
            self._prune_locked(now)
            for token, entry in tuple(self._pending.items()):
                if entry.mid != int(mid):
                    continue
                entry.acknowledged = True
                entry.expires_at = now + self.completed_grace_s
                self._pending.pop(token, None)
                self._completed[token] = entry
                return OwnMessageMatch(
                    matched_pending_own=True,
                    pending_age_s=max(0.0, now - entry.registered_at),
                    token=token,
                    kind=entry.kind,
                )
            for token, entry in self._completed.items():
                if entry.mid == int(mid):
                    entry.acknowledged = True
                    return OwnMessageMatch(
                        matched_completed_own=True,
                        pending_age_s=max(0.0, now - entry.registered_at),
                        token=token,
                        kind=entry.kind,
                    )
        return OwnMessageMatch()

    def counts(self) -> tuple[int, int]:
        now = self.clock()
        with self._lock:
            self._prune_locked(now)
            return len(self._pending), len(self._completed)


@dataclass(frozen=True)
class ClassifiedMqttMessage:
    classification: str
    retained: bool
    source: str | None
    session_id: str | None
    sequence: int | None
    payload_hash: str
    throttle: float | None
    steering: float | None
    release: bool
    qos: int
    matched_pending_own: bool
    matched_completed_own: bool
    pending_age_s: float | None


def classify_mqtt_message(
    raw_payload: str | bytes,
    *,
    retained: bool = False,
    qos: int = 0,
    own_registry: OwnMessageRegistry | None = None,
) -> ClassifiedMqttMessage:
    raw_bytes = (
        raw_payload.encode("utf-8")
        if isinstance(raw_payload, str)
        else bytes(raw_payload)
    )
    payload_hash = hashlib.sha256(raw_bytes).hexdigest()
    try:
        decoded = json.loads(raw_bytes)
    except (TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        decoded = None
    payload = decoded if isinstance(decoded, Mapping) else {}
    match = (
        own_registry.match(payload, payload_hash, retained=retained)
        if own_registry is not None and isinstance(decoded, Mapping)
        else OwnMessageMatch()
    )
    throttle = _finite_number(payload.get("throttle"))
    steering = _finite_number(payload.get("steering"))
    release = payload.get("release") is True
    if match.matched:
        classification = OWN_MQTT_ECHO
    elif (
        (throttle is not None and abs(throttle) > ZERO_EPSILON)
        or (steering is not None and abs(steering) > ZERO_EPSILON)
    ):
        classification = ACTIVE_FOREIGN_COMMAND
    elif release:
        classification = BENIGN_RELEASE
    elif (
        throttle is not None
        and steering is not None
        and abs(throttle) <= ZERO_EPSILON
        and abs(steering) <= ZERO_EPSILON
    ):
        classification = BENIGN_NEUTRAL
    else:
        classification = UNKNOWN_SCHEMA
    return ClassifiedMqttMessage(
        classification=classification,
        retained=bool(retained),
        source=_safe_identifier(payload.get("source")),
        session_id=_safe_identifier(payload.get("session_id")),
        sequence=_optional_sequence(payload.get("sequence")),
        payload_hash=payload_hash,
        throttle=throttle,
        steering=steering,
        release=release,
        qos=int(qos),
        matched_pending_own=match.matched_pending_own,
        matched_completed_own=match.matched_completed_own,
        pending_age_s=match.pending_age_s,
    )


class Transport(Protocol):
    connected: bool

    def publish(self, topic: str, payload: str, qos: int, retain: bool) -> Any: ...


@dataclass
class FakeTransport:
    connected: bool = True
    published: list[tuple[str, str, int, bool]] = field(default_factory=list)

    def publish(self, topic: str, payload: str, qos: int, retain: bool) -> int:
        if not self.connected:
            raise ConnectionError("fake transport disconnected")
        self.published.append((topic, payload, qos, retain))
        return len(self.published)


@dataclass(frozen=True)
class TrackedPublish:
    info: Any
    mid: int
    payload_hash: str
    token: int


def publish_action_tracked(
    transport: Transport,
    registry: OwnMessageRegistry,
    action: PublishAction,
    topic: str = SHARED_TOPIC,
) -> TrackedPublish:
    if action.retain:
        raise ValueError("retained MQTT publish is forbidden")
    raw = json.dumps(action.payload, separators=(",", ":"), sort_keys=True)
    payload_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    token = registry.register(action, payload_hash)
    try:
        info = transport.publish(
            topic,
            raw,
            qos=action.qos,
            retain=False,
        )
    except Exception:
        registry.discard(token)
        raise
    mid = int(getattr(info, "mid", info if isinstance(info, int) else -1))
    registry.bind_mid(token, mid)
    return TrackedPublish(
        info=info,
        mid=mid,
        payload_hash=payload_hash,
        token=token,
    )


class AdapterCore:
    """Session ownership, mapping, bounded neutral/release, and abort policy."""

    def __init__(self, limits: TestLimits | None = None, session_id: str | None = None,
                 neutral_repetitions: int = 3, release_repetitions: int = 3,
                 bounded_stop_neutral: bool = False,
                 release_without_extra_neutral: bool = False,
                 recoverable_permission_loss: bool = False):
        self.limits = limits or TestLimits()
        self.session_id = session_id or uuid.uuid4().hex
        self.sequence = 0
        self.held = False
        self.control_acquired = False
        self.control_ever_acquired = False
        self.post_release_flush_sent = False
        self.aborted = False
        self.abort_reason = ""
        self.neutral_repetitions = max(1, int(neutral_repetitions))
        self.release_repetitions = max(1, int(release_repetitions))
        self.bounded_stop_neutral = bool(bounded_stop_neutral)
        self.release_without_extra_neutral = bool(
            release_without_extra_neutral
        )
        self.recoverable_permission_loss = bool(
            recoverable_permission_loss
        )
        self.stop_neutral_sent = False

    def _payload(self, throttle: float | None = None, steering: float | None = None,
                 release: bool = False, now: float | None = None) -> dict[str, Any]:
        self.sequence += 1
        payload: dict[str, Any] = {
            "source": SOURCE_ID,
            "session_id": self.session_id,
            "sequence": self.sequence,
            "timestamp": float(time.time() if now is None else now),
        }
        if release:
            payload["release"] = True
        else:
            payload["throttle"] = float(throttle or 0.0)
            payload["steering"] = float(steering or 0.0)
        return payload

    def _action(self, kind: str, **kwargs: Any) -> PublishAction:
        return PublishAction(kind, self._payload(**kwargs), self.limits.mqtt_qos, False)

    def handle_classified(
        self,
        message: ClassifiedMqttMessage,
    ) -> list[PublishAction]:
        if message.classification == OWN_MQTT_ECHO:
            return []
        if message.retained:
            return self.abort("FOREIGN_RETAINED_MESSAGE", foreign=True)
        if message.classification in (BENIGN_RELEASE, BENIGN_NEUTRAL):
            return []
        if message.classification == ACTIVE_FOREIGN_COMMAND:
            reason = (
                "FOREIGN_ACTIVE_COMMAND_DURING_MOTION"
                if self.held
                else "FOREIGN_ACTIVE_COMMAND"
            )
            return self.abort(reason, foreign=True)
        return self.abort("FOREIGN_UNKNOWN_SCHEMA", foreign=True)

    def handle_incoming(
        self,
        raw_payload: str | bytes,
        *,
        retained: bool = False,
        qos: int = 0,
        own_registry: OwnMessageRegistry | None = None,
    ) -> list[PublishAction]:
        return self.handle_classified(
            classify_mqtt_message(
                raw_payload,
                retained=retained,
                qos=qos,
                own_registry=own_registry,
            )
        )

    def abort(self, reason: str, foreign: bool = False) -> list[PublishAction]:
        if self.aborted:
            return []
        self.aborted = True
        self.abort_reason = str(reason)
        if foreign:
            self.held = False
            self.control_acquired = False
            return [self._action("RELEASE", release=True)]
        actions = [self._action("NEUTRAL", throttle=0.0, steering=0.0)
                   for _ in range(self.neutral_repetitions)]
        actions.extend(self._action("RELEASE", release=True)
                       for _ in range(self.release_repetitions))
        self.held = False
        self.control_acquired = False
        return actions

    def relinquish(self, now: float | None = None) -> list[PublishAction]:
        """Release CA ownership without making the adapter terminal."""
        if self.aborted or not (self.held or self.control_acquired):
            return []

        self.held = False
        self.control_acquired = False
        self.stop_neutral_sent = False
        self.post_release_flush_sent = True

        return [
            self._action(
                "RELEASE",
                release=True,
                now=now,
            )
        ]

    def update(self, command: str, left: float, right: float, motion_allowed: bool,
               now: float | None = None) -> list[PublishAction]:
        if self.aborted:
            return []
        if not motion_allowed:
            if self.held or self.control_acquired:
                if self.recoverable_permission_loss:
                    return self.relinquish(now=now)
                return self.abort("MOTION_PERMISSION_LOST")
            if self.control_ever_acquired and not self.post_release_flush_sent:
                self.post_release_flush_sent = True
                if (
                    str(self.limits.mapping_profile or "").strip().upper()
                    == "SEAPORTAL_ACTUAL"
                ):
                    return []
                actions = [
                    self._action(
                        "NEUTRAL", throttle=0.0, steering=0.0, now=now
                    )
                    for _ in range(self.neutral_repetitions)
                ]
                actions.extend(
                    self._action("RELEASE", release=True, now=now)
                    for _ in range(self.release_repetitions)
                )
                return actions
            return []
        cmd, known, _ = normalize_command_details(command)
        if not known:
            return self.abort("SAFE_COMMAND_INVALID")
        throttle, steering, reason = command_to_test_output(cmd, left, right, self.limits)
        if reason != "VALID":
            return self.abort(reason)
        if cmd == "HOLD_COURSE":
            if not self.held:
                return []
            actions = []
            if not (
                self.release_without_extra_neutral
                and self.stop_neutral_sent
            ):
                actions.append(
                    self._action(
                        "NEUTRAL",
                        throttle=0.0,
                        steering=0.0,
                        now=now,
                    )
                )
            actions.append(self._action("RELEASE", release=True, now=now))
            self.held = False
            self.control_acquired = False
            self.stop_neutral_sent = False
            return actions
        if cmd == "STOP":
            self.held = True
            self.control_acquired = True
            self.control_ever_acquired = True
            self.post_release_flush_sent = False
            if self.bounded_stop_neutral:
                if self.stop_neutral_sent:
                    return []
                self.stop_neutral_sent = True
                return [
                    self._action(
                        "NEUTRAL",
                        throttle=0.0,
                        steering=0.0,
                        now=now,
                    )
                    for _ in range(self.neutral_repetitions)
                ]
            return [self._action("NEUTRAL", throttle=0.0, steering=0.0, now=now)]
        self.stop_neutral_sent = False
        self.held = True
        self.control_acquired = True
        self.control_ever_acquired = True
        self.post_release_flush_sent = False
        return [self._action("MOTION", throttle=throttle, steering=steering, now=now)]

    def hold_failsafe_stop(
        self,
        now: float | None = None,
    ) -> list[PublishAction]:
        """Replace an owned command with neutral without releasing ownership."""
        return self.update("STOP", 0.0, 0.0, True, now=now)

    def shutdown(self, now: float | None = None) -> list[PublishAction]:
        if self.aborted:
            return []
        if not self.held:
            return []
        actions = [self._action("NEUTRAL", throttle=0.0, steering=0.0, now=now)
                   for _ in range(self.neutral_repetitions)]
        actions.extend(self._action("RELEASE", release=True, now=now)
                       for _ in range(self.release_repetitions))
        self.held = False
        self.control_acquired = False
        return actions


def publish_actions(transport: Transport, actions: list[PublishAction], topic: str = SHARED_TOPIC) -> list[Any]:
    results = []
    for action in actions:
        if action.retain:
            raise ValueError("retained MQTT publish is forbidden")
        results.append(transport.publish(
            topic,
            json.dumps(action.payload, separators=(",", ":"), sort_keys=True),
            qos=action.qos,
            retain=False,
        ))
    return results
