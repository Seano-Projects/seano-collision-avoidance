"""Pure fail-closed state machine for the guarded AUTO takeover test."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence


HAZARD_COMMANDS = {
    "SLOW_DOWN",
    "TURN_LEFT_SLOW",
    "TURN_RIGHT_SLOW",
    "TURN_LEFT",
    "TURN_RIGHT",
    "STOP",
}


def classify_slow_effectiveness(
    requested_throttle: float,
    minimum_effective_throttle: float,
) -> tuple[str, str]:
    """Never infer physical thrust from an electronic RC observation."""
    if float(requested_throttle) < float(minimum_effective_throttle):
        return "NO", "SLOW_BELOW_EFFECTIVE_THRESHOLD"
    return "UNKNOWN", "PHYSICAL_EFFECT_UNKNOWN"


@dataclass
class AutoTakeoverInputs:
    now: float
    fcu_connected: bool = False
    fcu_armed: bool = False
    fcu_mode: str = "UNKNOWN"
    software_ready: bool = False
    perception_valid: bool = False
    perception_state: str = "UNKNOWN"
    camera_perception_available: bool = False
    manager_fresh: bool = False
    watchdog_fresh: bool = False
    risk_policy_valid: bool = False
    command_fresh: bool = False
    failsafe_active: bool = True
    desired_command: str = "STALE"
    safe_command: str = "STALE"
    selected_command: str = "STALE"
    mqtt_connected: bool = False
    web_video_available: bool = False
    adapter_fresh: bool = False
    hud_fresh: bool = False
    rc_publisher_count: int = 0
    rc_publisher_name: str = ""
    rc_subscriber_present: bool = False
    foreign_active: bool = False
    foreign_unknown: bool = False
    retained_foreign: bool = False
    neutral_sent: bool = False
    release_sent: bool = False
    release_echo_received: bool = False
    motion_sent: bool = False
    motion_command_sent: bool = False
    mqtt_ack_received: bool = False
    own_echo_received: bool = False
    rc_command_delivered: bool = False
    rc_neutral_confirmed: bool = False
    command_delivery_fresh: bool = False
    command_delivery_age_s: float = 0.0
    adapter_control_acquired: bool = False
    adapter_fault_reason: str = ""
    mission_status_known: bool = False
    mission_active: bool = True


@dataclass(frozen=True)
class AutoTakeoverOutput:
    state: str
    hardware_command: str
    command_publish_allowed: bool
    motion_allowed: bool
    actuator_path_ready: bool
    physical_ready: bool
    requested_mode: str
    mode_request_sent: bool
    mode_request_acknowledged: bool
    blocked_reason: str
    abort_reason: str


@dataclass
class RcCycleEvidence:
    """Current-cycle, read-only evidence from an external RC override topic."""

    steering_channel_index: int = 0
    throttle_channel_index: int = 2
    pwm_min: int = 1000
    neutral_throttle_pwm: int = 1500
    pwm_max: int = 2000
    cycle_id: int = 0
    pre_motion_channels: tuple[int, ...] | None = None
    observed_motion_channels: tuple[int, ...] | None = None
    pre_motion_throttle_channel: int | None = None
    pre_motion_steering_channel: int | None = None
    observed_throttle_channel: int | None = None
    observed_steering_channel: int | None = None
    requested_motion_throttle_percent: float | None = None
    requested_motion_steering_percent: float | None = None
    throttle_delta_from_pre_motion: int | None = None
    steering_delta_from_pre_motion: int | None = None
    rc_changed_from_pre_motion: bool = False
    rc_matches_requested_command: bool = False
    rc_command_delivered: bool = False
    neutral_observed: bool = False
    release_observed: bool = False

    PWM_TOLERANCE = 2

    def _channels(self, values: Sequence[int] | None) -> tuple[int, ...] | None:
        if values is None:
            return None
        channels = tuple(int(value) for value in values)
        required_index = max(
            int(self.steering_channel_index),
            int(self.throttle_channel_index),
        )
        if required_index < 0 or len(channels) <= required_index:
            return None
        return channels

    def reset(self, cycle_id: int) -> None:
        steering_index = self.steering_channel_index
        throttle_index = self.throttle_channel_index
        pwm_min = self.pwm_min
        neutral = self.neutral_throttle_pwm
        pwm_max = self.pwm_max
        self.__dict__.update(
            RcCycleEvidence(
                steering_channel_index=steering_index,
                throttle_channel_index=throttle_index,
                pwm_min=pwm_min,
                neutral_throttle_pwm=neutral,
                pwm_max=pwm_max,
                cycle_id=int(cycle_id),
            ).__dict__
        )

    def capture_pre_motion(self, channels: Sequence[int] | None) -> bool:
        values = self._channels(channels)
        if values is None:
            return False
        self.pre_motion_channels = values
        self.pre_motion_steering_channel = values[
            self.steering_channel_index
        ]
        self.pre_motion_throttle_channel = values[
            self.throttle_channel_index
        ]
        return True

    def reset_delivery(self) -> None:
        self.observed_motion_channels = None
        self.observed_throttle_channel = None
        self.observed_steering_channel = None
        self.requested_motion_throttle_percent = None
        self.requested_motion_steering_percent = None
        self.throttle_delta_from_pre_motion = None
        self.steering_delta_from_pre_motion = None
        self.rc_changed_from_pre_motion = False
        self.rc_matches_requested_command = False
        self.rc_command_delivered = False

    def observe(
        self,
        channels: Sequence[int],
        *,
        requested_throttle: float,
        requested_steering: float,
        motion_expected: bool,
    ) -> dict[str, Any]:
        values = self._channels(channels)
        if values is None:
            return self.status()
        steering_pwm = values[self.steering_channel_index]
        throttle_pwm = values[self.throttle_channel_index]
        neutral_now = (
            steering_pwm == self.neutral_throttle_pwm
            and throttle_pwm == self.neutral_throttle_pwm
        )
        release_now = all(value == 0 for value in values)
        self.neutral_observed |= neutral_now
        self.release_observed |= release_now
        current_matches = False
        if motion_expected and not release_now:
            record_observation = bool(
                not neutral_now or self.observed_motion_channels is None
            )
            if record_observation:
                self.requested_motion_throttle_percent = float(
                    requested_throttle
                )
                self.requested_motion_steering_percent = float(
                    requested_steering
                )
                self.observed_motion_channels = values
                self.observed_steering_channel = steering_pwm
                self.observed_throttle_channel = throttle_pwm
                if self.pre_motion_channels is not None:
                    self.steering_delta_from_pre_motion = (
                        steering_pwm - int(self.pre_motion_steering_channel)
                    )
                    self.throttle_delta_from_pre_motion = (
                        throttle_pwm - int(self.pre_motion_throttle_channel)
                    )
                    self.rc_changed_from_pre_motion |= bool(
                        self.steering_delta_from_pre_motion
                        or self.throttle_delta_from_pre_motion
                    )
            expected_throttle = self.neutral_throttle_pwm + round(
                (float(requested_throttle) / 100.0)
                * (self.pwm_max - self.neutral_throttle_pwm)
            )
            requested_steering_value = float(requested_steering)
            if requested_steering_value >= 0.0:
                expected_steering = self.neutral_throttle_pwm - round(
                    (requested_steering_value / 100.0)
                    * (self.neutral_throttle_pwm - self.pwm_min)
                )
            else:
                expected_steering = self.neutral_throttle_pwm + round(
                    (abs(requested_steering_value) / 100.0)
                    * (self.pwm_max - self.neutral_throttle_pwm)
                )
            matches = (
                abs(throttle_pwm - expected_throttle) <= self.PWM_TOLERANCE
                and abs(steering_pwm - expected_steering) <= self.PWM_TOLERANCE
            )
            current_matches = matches
            self.rc_matches_requested_command |= matches
            self.rc_command_delivered |= matches
        result = self.status()
        result["current_rc_matches_requested_command"] = current_matches
        return result

    def status(self) -> dict[str, Any]:
        return {
            "pre_motion_channels": self.pre_motion_channels,
            "steering_channel_index": self.steering_channel_index,
            "throttle_channel_index": self.throttle_channel_index,
            "pwm_min": self.pwm_min,
            "pwm_neutral": self.neutral_throttle_pwm,
            "pwm_max": self.pwm_max,
            "pre_motion_throttle_channel": self.pre_motion_throttle_channel,
            "pre_motion_steering_channel": self.pre_motion_steering_channel,
            "observed_motion_channels": self.observed_motion_channels,
            "observed_throttle_pwm": self.observed_throttle_channel,
            "observed_steering_pwm": self.observed_steering_channel,
            "requested_motion_throttle_percent": (
                self.requested_motion_throttle_percent
            ),
            "requested_motion_steering_percent": (
                self.requested_motion_steering_percent
            ),
            "throttle_delta_from_pre_motion": self.throttle_delta_from_pre_motion,
            "steering_delta_from_pre_motion": self.steering_delta_from_pre_motion,
            "rc_changed_from_pre_motion": self.rc_changed_from_pre_motion,
            "rc_matches_requested_command": self.rc_matches_requested_command,
            "rc_command_delivered": self.rc_command_delivered,
            "rc_delivery_status": (
                "RC_DELIVERED"
                if self.rc_command_delivered
                else "RC_NOT_DELIVERED"
            ),
            "neutral_observed": self.neutral_observed,
            "release_observed": self.release_observed,
        }


class AutoTakeoverCore:
    """Repeatable mode owner; never arms/disarms and never retries forever."""

    def __init__(
        self,
        *,
        started_at: float = 0.0,
        startup_grace_s: float = 8.0,
        hazard_debounce_s: float = 0.4,
        clear_hold_s: float = 2.5,
        mode_timeout_s: float = 3.0,
        maximum_motion_duration_s: float = 2.0,
        maximum_takeover_duration_s: float = 15.0,
        command_freshness_watchdog_s: float | None = None,
        motion_delivery_timeout_s: float = 0.75,
        release_timeout_s: float = 1.0,
        final_release_timeout_s: float = 0.5,
        maximum_mode_requests: int = 3,
        mode_retry_interval_s: float = 1.0,
        auto_rejoin_verify_s: float = 0.5,
    ) -> None:
        self.state = "STARTING"
        self.started_at = float(started_at)
        self.startup_grace_s = max(8.0, float(startup_grace_s))
        self.hazard_debounce_s = max(0.3, float(hazard_debounce_s))
        self.clear_hold_s = max(2.0, float(clear_hold_s))
        self.mode_timeout_s = max(0.5, float(mode_timeout_s))
        watchdog = (
            maximum_motion_duration_s
            if command_freshness_watchdog_s is None
            else command_freshness_watchdog_s
        )
        self.command_freshness_watchdog_s = min(
            2.0, max(0.1, float(watchdog))
        )
        self.maximum_motion_duration_s = self.command_freshness_watchdog_s
        self.motion_delivery_timeout_s = min(
            1.0, max(0.5, float(motion_delivery_timeout_s))
        )
        self.release_timeout_s = max(0.2, float(release_timeout_s))
        self.final_release_timeout_s = max(
            0.2, float(final_release_timeout_s)
        )
        self.maximum_takeover_duration_s = min(
            30.0,
            max(
                10.0,
                self.command_freshness_watchdog_s + self.clear_hold_s
                + (2.0 * self.mode_timeout_s),
                float(maximum_takeover_duration_s),
            ),
        )
        self.maximum_mode_requests = max(1, int(maximum_mode_requests))
        self.mode_retry_interval_s = max(
            1.0, float(mode_retry_interval_s)
        )
        self.auto_rejoin_verify_s = max(
            0.2, float(auto_rejoin_verify_s)
        )
        self.cycle_id = 0
        self.completed_cycle_count = 0
        self.session_mode_request_count = 0
        self.last_completed_cycle: dict[str, Any] = {}
        self._events: list[dict[str, Any]] = []
        self._mode_action = ""
        self.reset_cycle_state(self.started_at)
        self.blocked_reason = "STARTUP_GRACE"

    def reset_cycle_state(self, now: float) -> None:
        """Clear active-cycle data without changing session counters."""
        self.original_mode = ""
        self.takeover_owner = False
        self.manual_requested_by_ca = False
        self.control_ever_owned = False
        self.motion_ever_sent = False
        self.restore_auto_allowed = False
        self.requested_mode = ""
        self.mode_request_sent = False
        self.mode_request_acknowledged = False
        self.mode_request_count = 0
        self.mode_requested_at = 0.0
        self.manual_requested_at = 0.0
        self.auto_requested_at = 0.0
        self.hazard_started_at = 0.0
        self.first_hazard_at = 0.0
        self.manual_confirmed_at = 0.0
        self.motion_started_at = 0.0
        self.motion_pending_at = 0.0
        self.motion_delivery_confirmed_at = 0.0
        self.motion_delivery_evidence = ""
        self.motion_limit_reached_at = 0.0
        self.motion_limit_reached = False
        self.clear_started_at = 0.0
        self.clear_hold_completed = False
        self.neutralizing_started_at = 0.0
        self.release_started_at = 0.0
        self.release_final_attempted_at = 0.0
        self.auto_confirmed_at = 0.0
        self.auto_rejoin_started_at = 0.0
        self.auto_service_response = "NONE"
        self.auto_mode_observed = False
        self.auto_restore_pending = False
        self.auto_rejoin_verified = False
        self.cycle_takeover_started_at = 0.0
        self.last_hazard_command = "HOLD_COURSE"
        self.failsafe_stop_takeover = False
        self.failsafe_stop_reason = ""
        self.blocked_reason = ""
        self.abort_reason = ""
        self.last_event = ""
        self._mode_action = ""

    @staticmethod
    def _mode(value: str) -> str:
        return str(value or "").strip().upper()

    @staticmethod
    def _command(value: str) -> str:
        return str(value or "").strip().upper()

    def _abort(self, reason: str) -> None:
        self.state = "ABORTED"
        self.abort_reason = str(reason)
        self.blocked_reason = self.abort_reason
        self._mode_action = ""

    def _enter_operator_override(self, now: float, reason: str) -> None:
        """Relinquish CA ownership without making operator intervention fatal."""
        previous_state = self.state
        self.reset_cycle_state(now)
        self.state = "OPERATOR_OVERRIDE"
        self.blocked_reason = str(reason)
        self._event(
            "OPERATOR_OVERRIDE_ENTERED",
            now,
            reason=str(reason),
            previous_state=previous_state,
        )

    def _event(self, event: str, now: float, **data: Any) -> None:
        self.last_event = str(event)
        self._events.append(
            {
                "event": str(event),
                "event_time": float(now),
                "cycle_id": self.cycle_id,
                **data,
            }
        )

    def consume_events(self) -> list[dict[str, Any]]:
        events = self._events
        self._events = []
        return events

    def _start_clear_hold(self, now: float) -> None:
        self.clear_started_at = now
        self.state = "CLEAR_HOLD"
        self.blocked_reason = "CLEAR_HOLD"
        self._event("CLEAR_HOLD_STARTED", now)

    @staticmethod
    def _duration(end: float, start: float) -> float:
        if end <= 0.0 or start <= 0.0:
            return 0.0
        return max(0.0, float(end) - float(start))

    @staticmethod
    def _delivery_evidence(data: AutoTakeoverInputs) -> str:
        if data.motion_command_sent or data.motion_sent:
            return "MOTION_COMMAND_SENT"
        if data.mqtt_ack_received:
            return "MQTT_ACK_RECEIVED"
        if data.own_echo_received:
            return "MQTT_OWN_ECHO_RECEIVED"
        if data.rc_command_delivered:
            return "RC_COMMAND_DELIVERED"
        return ""

    def _begin_motion_pending(self, now: float, command: str) -> None:
        self.last_hazard_command = command
        self.motion_pending_at = now
        self.state = "MOTION_COMMAND_PENDING"
        self.blocked_reason = "WAIT_MOTION_DELIVERY"
        self._event("MOTION_COMMAND_PENDING", now, command=command)

    def _confirm_motion_delivery(
        self,
        now: float,
        evidence: str,
    ) -> None:
        self.motion_delivery_confirmed_at = now
        self.motion_delivery_evidence = evidence
        self.motion_started_at = now
        self.motion_ever_sent = True
        self.control_ever_owned = True
        self.state = "MOTION_ACTIVE"
        self.blocked_reason = ""
        self._event("MOTION_DELIVERY_CONFIRMED", now, evidence=evidence)

    def _enter_safe_stop(self, now: float, reason: str) -> None:
        self.state = "SAFE_NEUTRAL_WAIT_CLEAR"
        self.blocked_reason = str(reason)
        self._event("SAFE_NEUTRAL_WAIT_CLEAR", now, reason=reason)

    def _request_auto_restore(self, now: float) -> None:
        if not (
            self.original_mode == "AUTO"
            and self.takeover_owner
            and self.manual_requested_by_ca
            and self.restore_auto_allowed
            and (
                not self.failsafe_stop_takeover
                or self.clear_hold_completed
            )
        ):
            self._abort("AUTO_RESTORE_NOT_OWNED")
            return
        self.state = "AUTO_RESTORE_REQUESTED"
        self.mode_request_count = 0
        self.auto_restore_pending = True
        self.auto_service_response = "PENDING"
        self.blocked_reason = "AUTO_RESTORE_REQUESTED"
        self._request_mode("AUTO", now)

    def _retry_auto_restore(self, now: float) -> None:
        if self.mode_request_count >= self.maximum_mode_requests:
            self.state = "SAFE_MANUAL_WAIT_AUTO"
            self.blocked_reason = "AUTO_RESTORE_PENDING"
            return
        self.state = "AUTO_RESTORE_REQUESTED"
        self.blocked_reason = "AUTO_RESTORE_RETRY"
        self._event(
            "AUTO_RESTORE_RETRY",
            now,
            request_count=self.mode_request_count + 1,
        )
        self._request_mode("AUTO", now)

    def _begin_auto_rejoin(self, now: float) -> None:
        if not self.auto_mode_observed:
            self._event("AUTO_MODE_OBSERVED", now)
        self.auto_mode_observed = True
        self.auto_restore_pending = False
        self.auto_rejoin_started_at = now
        self.state = "AUTO_REJOIN_VERIFY"
        self.blocked_reason = "AUTO_REJOIN_VERIFY"
        self._event("AUTO_REJOIN_VERIFY_STARTED", now)

    def _hazard_returned_during_restore(
        self,
        data: AutoTakeoverInputs,
    ) -> bool:
        return bool(
            self._mode(data.fcu_mode) == "MANUAL"
            and self.takeover_owner
            and self.manual_requested_by_ca
            and self._hazard_valid(data)
        )

    def _resume_avoidance_from_restore(
        self,
        now: float,
        command: str,
    ) -> None:
        self.state = "AVOIDANCE_READY"
        self.last_hazard_command = command
        self.clear_started_at = 0.0
        self.clear_hold_completed = False
        self.neutralizing_started_at = 0.0
        self.release_started_at = 0.0
        self.release_final_attempted_at = 0.0
        self.auto_restore_pending = False
        self.auto_service_response = "NONE"
        self.auto_mode_observed = False
        self.auto_rejoin_verified = False
        self.requested_mode = ""
        self.mode_request_sent = False
        self.mode_request_acknowledged = False
        self.blocked_reason = ""
        self._event(
            "HAZARD_RETURNED_DURING_RESTORE",
            now,
            command=command,
        )

    def _auto_transition_valid(
        self,
        data: AutoTakeoverInputs,
        command: str,
    ) -> bool:
        return bool(
            self._mode(data.fcu_mode) == "AUTO"
            and data.fcu_armed
            and self._recovery_ready(data, command)
            and self.original_mode == "AUTO"
            and self.takeover_owner
            and self.manual_requested_by_ca
            and self.restore_auto_allowed
            and (
                not self.failsafe_stop_takeover
                or self.clear_hold_completed
            )
        )

    def _auto_confirmation_valid(self, data: AutoTakeoverInputs) -> bool:
        return bool(
            self._mode(data.fcu_mode) == "AUTO"
            and data.fcu_armed
            and self._recovery_ready(
                data,
                self._command(data.selected_command),
            )
            and self.original_mode == "AUTO"
            and self.takeover_owner
            and self.manual_requested_by_ca
            and (
                not self.failsafe_stop_takeover
                or self.clear_hold_completed
            )
        )

    def _complete_auto_restore(self, now: float) -> None:
        self.auto_confirmed_at = now
        self.takeover_owner = False
        self.restore_auto_allowed = False
        self.state = "AUTO_CONFIRMED"
        self.auto_rejoin_verified = True
        self.auto_restore_pending = False
        self.hazard_started_at = 0.0
        self.blocked_reason = ""
        duration = self._duration(now, self.cycle_takeover_started_at)
        self.completed_cycle_count += 1
        self.last_completed_cycle = {
            "cycle_id": self.cycle_id,
            "first_hazard_time": self.first_hazard_at,
            "manual_request_time": self.manual_requested_at,
            "manual_confirmed_time": self.manual_confirmed_at,
            "motion_pending_time": self.motion_pending_at,
            "motion_start_time": self.motion_started_at,
            "motion_delivery_evidence": self.motion_delivery_evidence,
            "clear_start_time": self.clear_started_at,
            "release_start_time": self.release_started_at,
            "auto_request_time": self.auto_requested_at,
            "auto_confirmed_time": now,
            "total_takeover_duration": duration,
        }
        self._event("AUTO_RESTORE_CONFIRMED", now)
        self._event("AUTO_REJOIN_VERIFIED", now)
        self._event("CYCLE_COMPLETED", now)
        self._event(
            "TOTAL_TAKEOVER_DURATION",
            now,
            total_takeover_duration_s=duration,
        )

    def _request_mode(self, mode: str, now: float) -> None:
        if self.mode_request_count >= self.maximum_mode_requests:
            if mode == "AUTO":
                self.state = "SAFE_MANUAL_WAIT_AUTO"
                self.blocked_reason = "AUTO_RESTORE_PENDING"
            else:
                self._abort(f"ABORTED_{mode}_RETRY_LIMIT")
            return
        self.requested_mode = mode
        self.mode_request_sent = True
        self.mode_request_acknowledged = False
        self.mode_request_count += 1
        self.session_mode_request_count += 1
        self.mode_requested_at = now
        if mode == "MANUAL":
            self.manual_requested_at = now
        elif mode == "AUTO":
            self.auto_requested_at = now
            self.auto_service_response = "PENDING"
            self.auto_restore_pending = True
            self._event(
                "AUTO_RESTORE_REQUEST_SENT",
                now,
                request_count=self.mode_request_count,
            )
        self._mode_action = mode

    def consume_mode_request(self) -> str:
        mode = self._mode_action
        self._mode_action = ""
        return mode

    def report_mode_request(self, mode: str, accepted: bool) -> None:
        if self._mode(mode) != self.requested_mode:
            return
        self.mode_request_acknowledged = bool(accepted)
        if not accepted:
            if self.requested_mode == "MANUAL":
                self._abort("ABORTED_MODE_CHANGE_FAILED")
            else:
                self.auto_service_response = "REJECTED"
                self.state = "AUTO_RESTORE_RETRY"
                self.blocked_reason = "AUTO_RESTORE_PENDING"
        elif self.requested_mode == "AUTO":
            self.auto_service_response = "ACCEPTED"

    def report_mode_service_unavailable(self, mode: str) -> None:
        if self._mode(mode) == "AUTO":
            self._abort("AUTO_MODE_SERVICE_UNAVAILABLE")
        else:
            self._abort("MODE_SERVICE_UNAVAILABLE")

    def _hazard_valid(self, data: AutoTakeoverInputs) -> bool:
        return (
            self._command(data.selected_command) in HAZARD_COMMANDS
            and data.command_fresh
            and data.perception_valid
            and data.risk_policy_valid
            and not data.failsafe_active
        )

    def _failsafe_stop_reason(self, data: AutoTakeoverInputs) -> str:
        perception_state = self._mode(data.perception_state)
        if not data.manager_fresh:
            return "MANAGER_STALE"
        if not data.watchdog_fresh:
            return "WATCHDOG_STALE"
        if perception_state == "LOST_PERCEPTION":
            return "LOST_PERCEPTION"
        if (
            not data.camera_perception_available
            or not data.perception_valid
        ):
            return "PERCEPTION_UNAVAILABLE"
        if not data.command_fresh:
            return "COMMAND_STALE"
        if data.failsafe_active:
            return "FAILSAFE_ACTIVE"
        return ""

    def _recovery_ready(
        self,
        data: AutoTakeoverInputs,
        command: str,
    ) -> bool:
        return bool(
            not self._failsafe_stop_reason(data)
            and command == "HOLD_COURSE"
            and data.command_fresh
            and data.perception_valid
            and data.camera_perception_available
            and data.manager_fresh
            and data.watchdog_fresh
            and data.risk_policy_valid
            and not data.failsafe_active
        )

    def _begin_takeover(
        self,
        now: float,
        command: str,
        *,
        first_hazard_at: float,
        failsafe_reason: str = "",
    ) -> None:
        self.reset_cycle_state(now)
        self.cycle_id += 1
        self.first_hazard_at = first_hazard_at
        self.hazard_started_at = first_hazard_at
        self.last_hazard_command = command
        self.failsafe_stop_takeover = bool(failsafe_reason)
        self.failsafe_stop_reason = str(failsafe_reason)
        self.state = "TAKEOVER_REQUESTED"
        self.original_mode = "AUTO"
        self.takeover_owner = True
        self.manual_requested_by_ca = True
        self.restore_auto_allowed = True
        self.cycle_takeover_started_at = now
        self._request_mode("MANUAL", now)
        self.blocked_reason = "WAIT_MANUAL_CONFIRMATION"
        if failsafe_reason:
            self._event(
                "FAILSAFE_STOP_TAKEOVER_REQUESTED",
                now,
                reason=failsafe_reason,
            )

    def _activate_fault_stop(
        self,
        now: float,
        reason: str,
    ) -> None:
        first_activation = not self.failsafe_stop_takeover
        self.failsafe_stop_takeover = True
        self.failsafe_stop_reason = str(reason)
        self.last_hazard_command = "STOP"
        if self.state != "MOTION_COMMAND_PENDING":
            self._begin_motion_pending(now, "STOP")
        else:
            self.motion_pending_at = now
            self.blocked_reason = "WAIT_STOP_DELIVERY"
        if first_activation:
            self._event(
                "FAILSAFE_STOP_ACTIVATED",
                now,
                reason=reason,
            )

    def _operational_reason(self, data: AutoTakeoverInputs) -> str:
        current_fault = self._failsafe_stop_reason(data)
        if self.failsafe_stop_takeover:
            reason = current_fault or self.failsafe_stop_reason
            if not current_fault:
                return "WAITING_FOR_PERCEPTION_RECOVERY"
            if reason in {"LOST_PERCEPTION", "PERCEPTION_UNAVAILABLE"}:
                return "LOST_PERCEPTION_STOP_TAKEOVER"
            return "FAILSAFE_STOP_TAKEOVER"
        if (
            self.state == "AUTO_MISSION_MONITORING"
            and self._command(data.selected_command) == "HOLD_COURSE"
            and not current_fault
        ):
            return "NORMAL_NO_OBSTACLE"
        return ""

    @staticmethod
    def _rc_ready(data: AutoTakeoverInputs) -> bool:
        return (
            data.rc_publisher_count == 1
            and data.rc_publisher_name == "/usv/thruster"
            and data.rc_subscriber_present
        )

    def _motion_gates(self, data: AutoTakeoverInputs) -> tuple[bool, str]:
        checks = (
            (data.fcu_connected, "FCU_DISCONNECTED"),
            (data.fcu_armed, "FCU_DISARMED"),
            (self._mode(data.fcu_mode) == "MANUAL", "MANUAL_NOT_CONFIRMED"),
            (data.perception_valid, "PERCEPTION_INVALID"),
            (data.command_fresh, "COMMAND_STALE"),
            (not data.failsafe_active, "FAILSAFE_ACTIVE"),
            (data.mqtt_connected, "MQTT_DISCONNECTED"),
            (data.web_video_available, "HUD_WEB_VIDEO_UNAVAILABLE"),
            (data.adapter_fresh, "ADAPTER_HEARTBEAT_STALE"),
            (data.hud_fresh, "HUD_HEARTBEAT_STALE"),
            (self._rc_ready(data), "RC_PATH_CHANGED"),
            (not data.foreign_active, "FOREIGN_ACTIVE_COMMAND"),
            (not data.foreign_unknown, "FOREIGN_UNKNOWN_SCHEMA"),
            (not data.retained_foreign, "FOREIGN_RETAINED_MESSAGE"),
            (
                not str(data.adapter_fault_reason or "").strip(),
                str(data.adapter_fault_reason or "ADAPTER_FAULT"),
            ),
        )
        for passed, reason in checks:
            if not passed:
                return False, reason
        return True, ""

    def _safe_stop_gates(self, data: AutoTakeoverInputs) -> bool:
        """Permit only zero-output STOP when motion freshness gates have closed."""
        return bool(
            data.fcu_connected
            and data.fcu_armed
            and self._mode(data.fcu_mode) == "MANUAL"
            and data.mqtt_connected
            and data.adapter_fresh
            and self._rc_ready(data)
            and not data.foreign_active
            and not data.foreign_unknown
            and not data.retained_foreign
            and not str(data.adapter_fault_reason or "").strip()
        )

    def _restore_path_fault(
        self,
        data: AutoTakeoverInputs,
    ) -> str:
        checks = (
            (data.fcu_connected, "FCU_DISCONNECTED"),
            (data.fcu_armed, "FCU_DISARMED"),
            (data.mqtt_connected, "MQTT_DISCONNECTED"),
            (data.adapter_fresh, "ADAPTER_HEARTBEAT_STALE"),
            (self._rc_ready(data), "RC_PATH_CHANGED"),
            (not data.foreign_active, "FOREIGN_ACTIVE_COMMAND"),
            (not data.foreign_unknown, "FOREIGN_UNKNOWN_SCHEMA"),
            (not data.retained_foreign, "FOREIGN_RETAINED_MESSAGE"),
            (
                not str(data.adapter_fault_reason or "").strip(),
                str(data.adapter_fault_reason or "ADAPTER_FAULT"),
            ),
        )
        for passed, reason in checks:
            if not passed:
                return reason
        return ""

    def _monitor_operator_mode(self, data: AutoTakeoverInputs) -> bool:
        mode = self._mode(data.fcu_mode)
        if mode in {"MANUAL", "AUTO"}:
            return True
        self.restore_auto_allowed = False
        self._abort("OPERATOR_MODE_INTERVENTION")
        return False

    def step(self, data: AutoTakeoverInputs) -> AutoTakeoverOutput:
        now = float(data.now)
        command = self._command(data.selected_command)
        if self.state == "ABORTED":
            return self.output(data)

        # Operator authority is non-terminal. MANUAL selection, DISARM, or
        # another operator-selected mode immediately removes CA ownership.
        # CA remains alive and may monitor again after AUTO + ARMED returns.
        operator_preemptible_states = {
            "AUTO_MISSION_MONITORING",
            "TAKEOVER_REQUESTED",
            "WAITING_FOR_MANUAL_CONFIRMATION",
            "AVOIDANCE_READY",
            "MOTION_COMMAND_PENDING",
            "MOTION_ACTIVE",
            "STOP_ACTIVE",
            "SAFE_NEUTRAL_WAIT_CLEAR",
            "CLEAR_HOLD",
            "NEUTRALIZING",
            "RELEASING_CONTROL",
            "RELEASE_FINAL_NEUTRAL",
            "RELEASE_FINAL_ATTEMPT",
            "AUTO_RESTORE_REQUESTED",
            "WAITING_FOR_AUTO_CONFIRMATION",
            "AUTO_RESTORE_RETRY",
            "SAFE_MANUAL_WAIT_AUTO",
            "AUTO_REJOIN_VERIFY",
        }

        manual_control_states = {
            "AVOIDANCE_READY",
            "MOTION_COMMAND_PENDING",
            "MOTION_ACTIVE",
            "STOP_ACTIVE",
            "SAFE_NEUTRAL_WAIT_CLEAR",
            "CLEAR_HOLD",
            "NEUTRALIZING",
            "RELEASING_CONTROL",
            "RELEASE_FINAL_NEUTRAL",
            "RELEASE_FINAL_ATTEMPT",
        }

        restore_states = {
            "AUTO_RESTORE_REQUESTED",
            "WAITING_FOR_AUTO_CONFIRMATION",
            "AUTO_RESTORE_RETRY",
            "SAFE_MANUAL_WAIT_AUTO",
        }

        mode = self._mode(data.fcu_mode)

        # Operator intervention dan safety fault adalah dua hal berbeda.
        #
        # MANUAL, DISARM, atau mode yang dipilih operator bersifat
        # recoverable. Namun ketika CA sedang mengambil, memiliki,
        # atau memulihkan control authority, fault pada FCU connection,
        # MQTT, adapter, RC path, foreign publisher, dan adapter fault
        # tetap harus fail-closed.
        safety_owned_states = (
            restore_states
            | {
                "AUTO_REJOIN_VERIFY",
            }
        )

        if self.state in safety_owned_states:
            safety_fault = self._restore_path_fault(data)

            # DISARM adalah operator authority / safety action,
            # sehingga tidak dibuat terminal.
            if safety_fault and safety_fault != "FCU_DISARMED":
                self._abort(safety_fault)
                return self.output(data)

        if self.state in operator_preemptible_states:
            # Hilangnya koneksi FCU tidak membunuh proses CA.
            # Sistem melepaskan authority dan menunggu FCU kembali.
            if not data.fcu_connected:
                self._enter_operator_override(now, "WAIT_FCU_CONNECTION")
                return self.output(data)

            # DISARM is an operator/safety action, not a permanent CA failure.
            if not data.fcu_armed:
                self._enter_operator_override(now, "WAIT_OPERATOR_ARM")
                return self.output(data)

            # While CA is only monitoring AUTO, any mode change belongs
            # to the operator.
            if self.state == "AUTO_MISSION_MONITORING" and mode != "AUTO":
                self._enter_operator_override(now, "WAIT_OPERATOR_AUTO")
                return self.output(data)

            # Once CA owns MANUAL for avoidance, a different mode means
            # the operator has taken authority back.
            if self.state in manual_control_states and mode != "MANUAL":
                self._enter_operator_override(now, "WAIT_OPERATOR_AUTO")
                return self.output(data)

            # AUTO had already been observed; going back to MANUAL here is
            # operator intervention and must not trigger another AUTO request.
            if self.state == "AUTO_REJOIN_VERIFY" and mode == "MANUAL":
                self._enter_operator_override(now, "WAIT_OPERATOR_AUTO")
                return self.output(data)

            # During AUTO restore, operator-selected RTL/HOLD/LOITER/etc.
            # must win without killing the CA process.
            if self.state in restore_states and mode not in {"AUTO", "MANUAL"}:
                self._enter_operator_override(now, "WAIT_OPERATOR_AUTO")
                return self.output(data)

            # If AUTO appears before the normal CA restore handshake is valid,
            # treat it as external/operator authority rather than terminal abort.
            if (
                self.state in restore_states
                and mode == "AUTO"
                and not self._auto_confirmation_valid(data)
            ):
                self._enter_operator_override(now, "WAIT_OPERATOR_AUTO")
                return self.output(data)

            if (
                self.state
                in {"TAKEOVER_REQUESTED", "WAITING_FOR_MANUAL_CONFIRMATION"}
                and mode not in {"AUTO", "MANUAL"}
            ):
                self._enter_operator_override(now, "WAIT_OPERATOR_AUTO")
                return self.output(data)

        if self.state == "STARTING":
            # Startup grace hanya memberi waktu node CA/HUD/watchdog hidup.
            # Kondisi mode dan arm FCU tidak menjadi syarat untuk menyalakan CA.
            self.blocked_reason = (
                "STARTUP_GRACE"
                if data.web_video_available
                else "HUD_WEB_VIDEO_UNAVAILABLE"
            )

            if now - self.started_at >= self.startup_grace_s:
                self.state = "WAITING_FOR_CA_READY"
                self.blocked_reason = (
                    "CA_NOT_READY"
                    if data.web_video_available
                    else "HUD_WEB_VIDEO_UNAVAILABLE"
                )
                self._event("STARTUP_GRACE_COMPLETED", now)

        elif self.state == "WAITING_FOR_CA_READY":
            # Persepsi dan seluruh software boleh menyala terlebih dahulu.
            # Tidak ada mode request dan tidak ada keluaran gerak di state ini.
            if not data.software_ready:
                self.blocked_reason = (
                    "HUD_WEB_VIDEO_UNAVAILABLE"
                    if not data.web_video_available
                    else "CA_NOT_READY"
                )

            elif data.mission_status_known and not data.mission_active:
                self.state = "MISSION_COMPLETE"
                self.blocked_reason = "MISSION_COMPLETE"
                self._event("MISSION_COMPLETE", now)

            elif (
                data.fcu_connected
                and self._mode(data.fcu_mode) == "AUTO"
                and data.fcu_armed
            ):
                # Sistem sudah sehat dan operator sudah menyediakan
                # AUTO + ARMED. CA menjadi eligible untuk monitoring/takeover.
                self.reset_cycle_state(now)
                self.state = "AUTO_MISSION_MONITORING"
                self.blocked_reason = ""
                self._event("CA_READY_AUTO_MONITORING", now)

            else:
                # Software CA sudah siap, tetapi authority masih di operator.
                if not data.fcu_connected:
                    reason = "WAIT_FCU_CONNECTION"
                elif self._mode(data.fcu_mode) != "AUTO":
                    reason = "WAIT_OPERATOR_AUTO"
                elif not data.fcu_armed:
                    reason = "WAIT_OPERATOR_ARM"
                else:
                    reason = "CONTROL_STANDBY"

                self._enter_operator_override(now, reason)
                self._event(
                    "CA_READY_CONTROL_STANDBY",
                    now,
                    reason=reason,
                )

        elif self.state == "OPERATOR_OVERRIDE":
            mode = self._mode(data.fcu_mode)

            # Pipeline CA tetap hidup. Yang ditahan hanya control authority.
            if not data.software_ready:
                self.blocked_reason = (
                    "HUD_WEB_VIDEO_UNAVAILABLE"
                    if not data.web_video_available
                    else "CA_NOT_READY"
                )

            elif not data.fcu_connected:
                self.blocked_reason = "WAIT_FCU_CONNECTION"

            elif mode != "AUTO":
                self.blocked_reason = "WAIT_OPERATOR_AUTO"

            elif not data.fcu_armed:
                self.blocked_reason = "WAIT_OPERATOR_ARM"

            elif data.mission_status_known and not data.mission_active:
                self.state = "MISSION_COMPLETE"
                self.blocked_reason = "MISSION_COMPLETE"
                self._event("MISSION_COMPLETE", now)

            else:
                # AUTO + ARMED + software healthy.
                # Tidak peduli berapa kali operator sebelumnya MANUAL,
                # DISARM, ARM ulang, atau kembali AUTO.
                self.reset_cycle_state(now)
                self.state = "AUTO_MISSION_MONITORING"
                self.blocked_reason = ""
                self._event("OPERATOR_OVERRIDE_RELEASED", now)
                self._event("RETURNED_TO_AUTO_MONITORING", now)

        elif self.state == "AUTO_MISSION_MONITORING":
            fault_reason = self._failsafe_stop_reason(data)
            if not data.fcu_connected:
                self._abort("FCU_DISCONNECTED")
            elif not data.fcu_armed:
                self._abort("FCU_DISARMED")
            elif self._mode(data.fcu_mode) != "AUTO":
                self._abort("OPERATOR_MODE_INTERVENTION")
            elif data.mission_status_known and not data.mission_active:
                self.state = "MISSION_COMPLETE"
                self.blocked_reason = "MISSION_COMPLETE"
                self._event("MISSION_COMPLETE", now)
            elif fault_reason:
                self._begin_takeover(
                    now,
                    "STOP",
                    first_hazard_at=now,
                    failsafe_reason=fault_reason,
                )
            elif self._hazard_valid(data):
                if self.hazard_started_at <= 0.0:
                    self.hazard_started_at = now
                    self.last_hazard_command = command
                elif now - self.hazard_started_at >= self.hazard_debounce_s:
                    first_hazard_at = self.hazard_started_at
                    hazard_command = command
                    self._begin_takeover(
                        now,
                        hazard_command,
                        first_hazard_at=first_hazard_at,
                    )
            else:
                self.hazard_started_at = 0.0

        elif self.state == "TAKEOVER_REQUESTED":
            self.state = "WAITING_FOR_MANUAL_CONFIRMATION"

        elif self.state == "WAITING_FOR_MANUAL_CONFIRMATION":
            mode = self._mode(data.fcu_mode)
            if not data.fcu_armed:
                self._abort("FCU_DISARMED")
            elif mode == "MANUAL":
                self.manual_confirmed_at = now
                self.state = "AVOIDANCE_READY"
                self.blocked_reason = ""
            elif mode != "AUTO":
                self.restore_auto_allowed = False
                self._abort("OPERATOR_MODE_INTERVENTION")
            elif now - self.mode_requested_at > self.mode_timeout_s:
                self._abort("ABORTED_MODE_CHANGE_TIMEOUT")

        elif self.state == "AVOIDANCE_READY":
            mode = self._mode(data.fcu_mode)
            if mode != "MANUAL":
                self.restore_auto_allowed = False
                self._abort(
                    "MODE_CHANGED_BEFORE_RELEASE"
                    if mode == "AUTO"
                    else "OPERATOR_MODE_INTERVENTION"
                )
            else:
                fault_reason = self._failsafe_stop_reason(data)
                if self.failsafe_stop_takeover or fault_reason:
                    self._activate_fault_stop(
                        now,
                        fault_reason
                        or self.failsafe_stop_reason
                        or "FAILSAFE_ACTIVE",
                    )
                else:
                    ready, reason = self._motion_gates(data)
                if (
                    not self.failsafe_stop_takeover
                    and not fault_reason
                    and not ready
                ):
                    self.blocked_reason = reason
                    if data.adapter_fault_reason or reason in {
                        "FCU_DISCONNECTED",
                        "FCU_DISARMED",
                        "FAILSAFE_ACTIVE",
                        "FOREIGN_ACTIVE_COMMAND",
                        "FOREIGN_UNKNOWN_SCHEMA",
                        "FOREIGN_RETAINED_MESSAGE",
                        "RC_PATH_CHANGED",
                    }:
                        self._abort(reason)
                elif self.failsafe_stop_takeover:
                    pass
                elif command == "HOLD_COURSE" and data.perception_valid:
                    self._start_clear_hold(now)
                elif not self._hazard_valid(data):
                    self._enter_safe_stop(
                        now, "HAZARD_NOT_VALID_AFTER_TAKEOVER"
                    )
                else:
                    self._begin_motion_pending(now, command)

        elif self.state == "MOTION_COMMAND_PENDING":
            mode = self._mode(data.fcu_mode)
            if mode != "MANUAL":
                self.restore_auto_allowed = False
                self._abort(
                    "MODE_CHANGED_BEFORE_RELEASE"
                    if mode == "AUTO"
                    else "OPERATOR_MODE_INTERVENTION"
                )
            else:
                fault_reason = self._failsafe_stop_reason(data)
                if fault_reason and not self.failsafe_stop_takeover:
                    self._activate_fault_stop(now, fault_reason)
                if self.failsafe_stop_takeover:
                    ready = self._safe_stop_gates(data)
                    reason = (
                        ""
                        if ready
                        else "SAFE_STOP_PATH_NOT_READY"
                    )
                else:
                    ready, reason = self._motion_gates(data)
                if not ready:
                    if self.failsafe_stop_takeover:
                        self.blocked_reason = reason
                    elif reason in {"PERCEPTION_INVALID", "COMMAND_STALE"}:
                        self._activate_fault_stop(now, reason)
                    else:
                        self._abort(reason)
                elif self.failsafe_stop_takeover:
                    stop_commanded = bool(
                        data.neutral_sent
                        or data.adapter_control_acquired
                    )
                    if stop_commanded and data.rc_command_delivered:
                        self.control_ever_owned = bool(
                            data.adapter_control_acquired
                            or data.neutral_sent
                        )
                        self.state = "STOP_ACTIVE"
                        self.blocked_reason = "STOP_OVERRIDE_ACTIVE"
                        self._event(
                            "FAILSAFE_STOP_DELIVERED",
                            now,
                            reason=self.failsafe_stop_reason,
                        )
                    elif stop_commanded:
                        self.blocked_reason = "WAIT_STOP_RC_DELIVERY"
                    elif (
                        now - self.motion_pending_at
                        >= self.motion_delivery_timeout_s
                    ):
                        self.blocked_reason = "WAIT_STOP_DELIVERY"
                        self._event("STOP_DELIVERY_PENDING", now)
                elif command == "HOLD_COURSE":
                    self._start_clear_hold(now)
                elif not self._hazard_valid(data):
                    self._enter_safe_stop(now, "HAZARD_NOT_VALID")
                elif command == "STOP":
                    stop_commanded = bool(
                        data.neutral_sent
                        or data.adapter_control_acquired
                    )
                    if stop_commanded and data.rc_command_delivered:
                        self.control_ever_owned = bool(
                            data.adapter_control_acquired
                            or data.neutral_sent
                        )
                        self.state = "STOP_ACTIVE"
                        self.blocked_reason = "STOP_OVERRIDE_ACTIVE"
                        self._event("STOP_COMMAND_DELIVERED", now)
                    elif stop_commanded:
                        self.blocked_reason = "WAIT_STOP_RC_DELIVERY"
                    elif (
                        now - self.motion_pending_at
                        >= self.motion_delivery_timeout_s
                    ):
                        self._event("MOTION_DELIVERY_TIMEOUT", now)
                        self._enter_safe_stop(
                            now, "MOTION_DELIVERY_TIMEOUT"
                        )
                else:
                    evidence = self._delivery_evidence(data)
                    if evidence:
                        self._confirm_motion_delivery(now, evidence)
                    elif (
                        now - self.motion_pending_at
                        >= self.motion_delivery_timeout_s
                    ):
                        self._event("MOTION_DELIVERY_TIMEOUT", now)
                        self._enter_safe_stop(
                            now, "MOTION_DELIVERY_TIMEOUT"
                        )

        elif self.state == "MOTION_ACTIVE":
            mode = self._mode(data.fcu_mode)
            if mode != "MANUAL":
                self.restore_auto_allowed = False
                self._abort(
                    "MODE_CHANGED_BEFORE_RELEASE"
                    if mode == "AUTO"
                    else "OPERATOR_MODE_INTERVENTION"
                )
                ready, reason = False, self.abort_reason
            else:
                fault_reason = self._failsafe_stop_reason(data)
                if fault_reason:
                    self._activate_fault_stop(now, fault_reason)
                    ready, reason = True, ""
                else:
                    ready, reason = self._motion_gates(data)
            if (
                self.state != "ABORTED"
                and not self.failsafe_stop_takeover
                and not ready
            ):
                if reason in {"PERCEPTION_INVALID", "COMMAND_STALE"}:
                    self._activate_fault_stop(now, reason)
                else:
                    self._abort(reason)
            if (
                self.state != "ABORTED"
                and not self.failsafe_stop_takeover
            ):
                if command == "HOLD_COURSE" and data.perception_valid:
                    self._start_clear_hold(now)
                elif command == "STOP" and self._hazard_valid(data):
                    self.last_hazard_command = "STOP"
                    self.state = "STOP_ACTIVE"
                    self.blocked_reason = "STOP_OVERRIDE_ACTIVE"
                elif self._hazard_valid(data):
                    self.last_hazard_command = command
                    if not data.command_delivery_fresh:
                        self._enter_safe_stop(
                            now, "COMMAND_DELIVERY_STALE"
                        )
                else:
                    self._enter_safe_stop(now, "HAZARD_NOT_VALID")

        elif self.state == "STOP_ACTIVE":
            mode = self._mode(data.fcu_mode)
            if mode != "MANUAL":
                self.restore_auto_allowed = False
                self._abort(
                    "MODE_CHANGED_BEFORE_RELEASE"
                    if mode == "AUTO"
                    else "OPERATOR_MODE_INTERVENTION"
                )
            elif (
                self.failsafe_stop_takeover
                or self._failsafe_stop_reason(data)
            ):
                fault_reason = self._failsafe_stop_reason(data)
                if fault_reason and not self.failsafe_stop_takeover:
                    self._activate_fault_stop(now, fault_reason)
                elif fault_reason:
                    self.failsafe_stop_reason = fault_reason
                fault_reason = self._failsafe_stop_reason(data)
                safe_stop_ready = self._safe_stop_gates(data)
                if fault_reason:
                    self.failsafe_stop_reason = fault_reason
                    self.blocked_reason = "STOP_OVERRIDE_ACTIVE"
                elif not self._recovery_ready(data, command):
                    self.blocked_reason = (
                        "WAITING_FOR_PERCEPTION_RECOVERY"
                    )
                elif not safe_stop_ready:
                    self.blocked_reason = "SAFE_STOP_PATH_NOT_READY"
                else:
                    self._start_clear_hold(now)
            else:
                ready, reason = self._motion_gates(data)
                if not ready:
                    if reason in {"PERCEPTION_INVALID", "COMMAND_STALE"}:
                        self._activate_fault_stop(now, reason)
                    elif reason == "FAILSAFE_ACTIVE":
                        self._activate_fault_stop(now, reason)
                    else:
                        self._abort(reason)
                elif command == "HOLD_COURSE":
                    self._start_clear_hold(now)
                elif command == "STOP" and self._hazard_valid(data):
                    self.blocked_reason = "STOP_OVERRIDE_ACTIVE"
                elif self._hazard_valid(data):
                    self.state = "AVOIDANCE_READY"
                    self.last_hazard_command = command
                    self.blocked_reason = ""
                else:
                    self._enter_safe_stop(now, "HAZARD_NOT_VALID")

        elif self.state == "SAFE_NEUTRAL_WAIT_CLEAR":
            mode = self._mode(data.fcu_mode)
            if mode != "MANUAL":
                self.restore_auto_allowed = False
                self._abort(
                    "MODE_CHANGED_BEFORE_RELEASE"
                    if mode == "AUTO"
                    else "OPERATOR_MODE_INTERVENTION"
                )
                ready, reason = False, self.abort_reason
            else:
                fault_reason = self._failsafe_stop_reason(data)
                if fault_reason:
                    self.failsafe_stop_takeover = True
                    self.failsafe_stop_reason = fault_reason
                    self.last_hazard_command = "STOP"
                if self.failsafe_stop_takeover:
                    ready = self._safe_stop_gates(data)
                    reason = (
                        ""
                        if ready
                        else "SAFE_STOP_PATH_NOT_READY"
                    )
                else:
                    ready, reason = self._motion_gates(data)
            if (
                self.state != "ABORTED"
                and not ready
                and self.failsafe_stop_takeover
            ):
                self.blocked_reason = reason
            elif self.state != "ABORTED" and not ready:
                if reason in {"PERCEPTION_INVALID", "COMMAND_STALE"}:
                    self._activate_fault_stop(now, reason)
                else:
                    self._abort(reason)
            elif self.state == "ABORTED":
                pass
            elif self.failsafe_stop_takeover:
                if (
                    self._recovery_ready(data, command)
                    and (data.neutral_sent or data.adapter_control_acquired)
                ):
                    self.state = "STOP_ACTIVE"
                    self.blocked_reason = (
                        "WAITING_FOR_PERCEPTION_RECOVERY"
                    )
                else:
                    self.blocked_reason = "STOP_OVERRIDE_ACTIVE"
            elif command == "HOLD_COURSE" and data.perception_valid:
                self._start_clear_hold(now)
            elif self._hazard_valid(data):
                self.last_hazard_command = command
                self.state = "AVOIDANCE_READY"
                self.blocked_reason = ""
            else:
                self.blocked_reason = (
                    self.blocked_reason or "SAFE_NEUTRAL_WAIT_CLEAR"
                )

        elif self.state == "CLEAR_HOLD":
            mode = self._mode(data.fcu_mode)
            fault_reason = self._failsafe_stop_reason(data)
            if fault_reason or (
                self.failsafe_stop_takeover
                and not self._recovery_ready(data, command)
            ):
                self.failsafe_stop_takeover = True
                self.clear_started_at = 0.0
                if fault_reason:
                    self.failsafe_stop_reason = fault_reason
                self.last_hazard_command = "STOP"
                self.state = "STOP_ACTIVE"
                self.blocked_reason = "STOP_OVERRIDE_ACTIVE"
                self._event(
                    "CLEAR_HOLD_CANCELLED_FAULT_RETURNED",
                    now,
                    reason=fault_reason or "RECOVERY_NOT_STABLE",
                )
                ready, reason = True, ""
            elif mode != "MANUAL":
                self.restore_auto_allowed = False
                self._abort(
                    "OPERATOR_MODE_INTERVENTION"
                )
                ready, reason = False, self.abort_reason
            else:
                ready, reason = self._motion_gates(data)
            if self.state != "ABORTED" and not ready:
                self._abort(reason)
            elif self.state == "ABORTED":
                pass
            elif self.state == "STOP_ACTIVE":
                pass
            elif self._hazard_valid(data):
                self._resume_avoidance_from_restore(now, command)
            elif not data.perception_valid or command != "HOLD_COURSE":
                self.clear_started_at = now
            elif now - self.clear_started_at >= self.clear_hold_s:
                self.clear_hold_completed = True
                self.neutralizing_started_at = now
                self.state = "NEUTRALIZING"
                self.blocked_reason = "WAIT_NEUTRAL_RC_CONFIRMATION"
                self._event("CLEAR_HOLD_COMPLETED", now)

        elif self.state == "NEUTRALIZING":
            mode = self._mode(data.fcu_mode)
            fault_reason = self._failsafe_stop_reason(data)
            path_fault = self._restore_path_fault(data)
            if path_fault:
                self._abort(path_fault)
            elif mode != "MANUAL":
                self.restore_auto_allowed = False
                self._abort("OPERATOR_MODE_INTERVENTION")
            elif fault_reason:
                self.failsafe_stop_takeover = True
                self.failsafe_stop_reason = fault_reason
                self.last_hazard_command = "STOP"
                self.state = "STOP_ACTIVE"
                self.blocked_reason = "STOP_OVERRIDE_ACTIVE"
            elif self._hazard_valid(data):
                self._resume_avoidance_from_restore(now, command)
            elif data.neutral_sent and data.rc_neutral_confirmed:
                self.release_started_at = now
                self.state = "RELEASING_CONTROL"
                self.blocked_reason = "WAIT_RELEASE_CONFIRMATION"
                self._event("NEUTRAL_RC_CONFIRMED", now)
            elif not data.neutral_sent:
                self.blocked_reason = "WAIT_NEUTRAL"
            else:
                self.blocked_reason = "WAIT_NEUTRAL_RC_CONFIRMATION"

        elif self.state == "RELEASING_CONTROL":
            mode = self._mode(data.fcu_mode)
            fault_reason = self._failsafe_stop_reason(data)
            path_fault = self._restore_path_fault(data)
            if path_fault:
                self._abort(path_fault)
            elif fault_reason and not data.release_sent:
                self.failsafe_stop_takeover = True
                self.failsafe_stop_reason = fault_reason
                self.last_hazard_command = "STOP"
                self.state = "STOP_ACTIVE"
                self.blocked_reason = "STOP_OVERRIDE_ACTIVE"
                self._event(
                    "RELEASE_CANCELLED_FAULT_RETURNED",
                    now,
                    reason=fault_reason,
                )
            elif mode != "MANUAL":
                self.restore_auto_allowed = False
                self._abort("OPERATOR_MODE_INTERVENTION")
            elif self._hazard_valid(data) and not data.release_sent:
                self._resume_avoidance_from_restore(now, command)
            elif data.release_sent and data.release_echo_received:
                self._request_auto_restore(now)
            elif data.release_sent:
                self.blocked_reason = "WAIT_RELEASE_OWN_ECHO"
            else:
                self.blocked_reason = "WAIT_RELEASE"

        elif self.state == "RELEASE_FINAL_NEUTRAL":
            fault_reason = self._failsafe_stop_reason(data)
            if fault_reason and not data.release_sent:
                self.failsafe_stop_takeover = True
                self.failsafe_stop_reason = fault_reason
                self.last_hazard_command = "STOP"
                self.state = "STOP_ACTIVE"
                self.blocked_reason = "STOP_OVERRIDE_ACTIVE"
            elif self._auto_transition_valid(data, command):
                self._complete_auto_restore(now)
            elif self._mode(data.fcu_mode) != "MANUAL":
                self.restore_auto_allowed = False
                self._abort("OPERATOR_MODE_INTERVENTION")
            elif self._hazard_valid(data):
                self.state = "AVOIDANCE_READY"
                self.last_hazard_command = command
                self.blocked_reason = ""
            else:
                self.state = "RELEASE_FINAL_ATTEMPT"
                self.release_final_attempted_at = now
                self.blocked_reason = "RELEASE_FINAL_ATTEMPT"

        elif self.state == "RELEASE_FINAL_ATTEMPT":
            fault_reason = self._failsafe_stop_reason(data)
            if fault_reason and not data.release_sent:
                self.failsafe_stop_takeover = True
                self.failsafe_stop_reason = fault_reason
                self.last_hazard_command = "STOP"
                self.state = "STOP_ACTIVE"
                self.blocked_reason = "STOP_OVERRIDE_ACTIVE"
            elif self._auto_transition_valid(data, command):
                self._complete_auto_restore(now)
            elif self._mode(data.fcu_mode) != "MANUAL":
                self.restore_auto_allowed = False
                self._abort("OPERATOR_MODE_INTERVENTION")
            elif self._hazard_valid(data):
                self.state = "AVOIDANCE_READY"
                self.last_hazard_command = command
                self.blocked_reason = ""
            elif data.release_sent:
                self._request_auto_restore(now)
            elif (
                now - self.release_final_attempted_at
                >= self.final_release_timeout_s
            ):
                self._abort("RELEASE_TIMEOUT_AFTER_FINAL_ATTEMPT")
            else:
                self.blocked_reason = "WAIT_FINAL_RELEASE"

        elif self.state == "AUTO_RESTORE_REQUESTED":
            mode = self._mode(data.fcu_mode)
            fault_reason = self._failsafe_stop_reason(data)
            path_fault = self._restore_path_fault(data)
            if path_fault:
                self._abort(path_fault)
            elif fault_reason and mode == "MANUAL":
                self.failsafe_stop_takeover = True
                self.failsafe_stop_reason = fault_reason
                self.last_hazard_command = "STOP"
                self.state = "STOP_ACTIVE"
                self.blocked_reason = "STOP_OVERRIDE_ACTIVE"
            elif self._auto_confirmation_valid(data):
                self._begin_auto_rejoin(now)
            elif mode == "MANUAL" and self.auto_service_response == "ACCEPTED":
                self.state = "WAITING_FOR_AUTO_CONFIRMATION"
                self.blocked_reason = "AUTO_RESTORE_PENDING"
            elif mode == "MANUAL" and self.auto_service_response == "REJECTED":
                self.state = "AUTO_RESTORE_RETRY"
                self.blocked_reason = "AUTO_RESTORE_PENDING"
            elif (
                mode == "MANUAL"
                and now - self.mode_requested_at > self.mode_timeout_s
            ):
                self.state = "AUTO_RESTORE_RETRY"
                self.blocked_reason = "AUTO_RESTORE_PENDING"
            elif mode == "MANUAL":
                self.blocked_reason = "AUTO_RESTORE_PENDING"
            else:
                self.restore_auto_allowed = False
                self._abort("OPERATOR_MODE_INTERVENTION")

        elif self.state == "WAITING_FOR_AUTO_CONFIRMATION":
            mode = self._mode(data.fcu_mode)
            fault_reason = self._failsafe_stop_reason(data)
            path_fault = self._restore_path_fault(data)
            if path_fault:
                self._abort(path_fault)
            elif fault_reason and mode == "MANUAL":
                self.failsafe_stop_takeover = True
                self.failsafe_stop_reason = fault_reason
                self.last_hazard_command = "STOP"
                self.state = "STOP_ACTIVE"
                self.blocked_reason = "STOP_OVERRIDE_ACTIVE"
            elif self._auto_confirmation_valid(data):
                self._begin_auto_rejoin(now)
            elif mode != "MANUAL":
                self.restore_auto_allowed = False
                self._abort("OPERATOR_MODE_INTERVENTION")
            elif now - self.mode_requested_at > self.mode_timeout_s:
                self.state = "AUTO_RESTORE_RETRY"
                self.blocked_reason = "AUTO_RESTORE_PENDING"

        elif self.state == "AUTO_RESTORE_RETRY":
            mode = self._mode(data.fcu_mode)
            path_fault = self._restore_path_fault(data)
            if path_fault:
                self._abort(path_fault)
            elif self._hazard_returned_during_restore(data):
                self._resume_avoidance_from_restore(now, command)
            elif self._auto_confirmation_valid(data):
                self._begin_auto_rejoin(now)
            elif mode != "MANUAL":
                self.restore_auto_allowed = False
                self._abort("OPERATOR_MODE_INTERVENTION")
            elif (
                now - self.mode_requested_at
                >= self.mode_retry_interval_s
            ):
                self._retry_auto_restore(now)
            else:
                self.blocked_reason = "AUTO_RESTORE_PENDING"

        elif self.state == "SAFE_MANUAL_WAIT_AUTO":
            mode = self._mode(data.fcu_mode)
            path_fault = self._restore_path_fault(data)
            if path_fault:
                self._abort(path_fault)
            elif self._hazard_returned_during_restore(data):
                self._resume_avoidance_from_restore(now, command)
            elif self._auto_confirmation_valid(data):
                self._begin_auto_rejoin(now)
            elif mode != "MANUAL":
                self.restore_auto_allowed = False
                self._abort("OPERATOR_MODE_INTERVENTION")
            else:
                self.blocked_reason = "AUTO_RESTORE_PENDING"

        elif self.state == "AUTO_REJOIN_VERIFY":
            mode = self._mode(data.fcu_mode)
            path_fault = self._restore_path_fault(data)
            if path_fault:
                self._abort(path_fault)
            elif mode == "MANUAL":
                self.auto_mode_observed = False
                self.auto_rejoin_started_at = 0.0
                self.state = "AUTO_RESTORE_RETRY"
                self.blocked_reason = "AUTO_RESTORE_PENDING"
            elif mode != "AUTO":
                self.restore_auto_allowed = False
                self._abort("OPERATOR_MODE_INTERVENTION")
            elif not self._recovery_ready(data, command):
                self.blocked_reason = "AUTO_REJOIN_WAIT_HEALTHY"
            elif (
                now - self.auto_rejoin_started_at
                >= self.auto_rejoin_verify_s
            ):
                self._complete_auto_restore(now)

        elif self.state == "AUTO_CONFIRMED":
            completed_cycle_id = self.cycle_id
            self.reset_cycle_state(now)
            self._event(
                "CYCLE_STATE_RESET",
                now,
                completed_cycle_id=completed_cycle_id,
            )
            if data.mission_status_known and not data.mission_active:
                self.state = "MISSION_COMPLETE"
                self.blocked_reason = "MISSION_COMPLETE"
                self._event("MISSION_COMPLETE", now)
            else:
                self.state = "AUTO_MISSION_MONITORING"
                self.blocked_reason = ""
                self._event("RETURNED_TO_AUTO_MONITORING", now)

        elif self.state == "MISSION_COMPLETE":
            self.takeover_owner = False
            self.restore_auto_allowed = False
            self.blocked_reason = "MISSION_COMPLETE"

        return self.output(data)

    def output(self, data: AutoTakeoverInputs) -> AutoTakeoverOutput:
        physical_ready, _ = self._motion_gates(data)
        safe_stop_ready = self._safe_stop_gates(data)
        command_publish_allowed = (
            (
                self.state
                in {"MOTION_COMMAND_PENDING", "MOTION_ACTIVE", "STOP_ACTIVE"}
                and (
                    physical_ready
                    or (self.failsafe_stop_takeover and safe_stop_ready)
                )
            )
            or (
                self.state
                in {
                    "CLEAR_HOLD",
                    "NEUTRALIZING",
                    "SAFE_NEUTRAL_WAIT_CLEAR",
                    "RELEASE_FINAL_NEUTRAL",
                }
                and safe_stop_ready
            )
        )
        motion_allowed = bool(
            self.state == "MOTION_ACTIVE"
            and physical_ready
            and data.command_delivery_fresh
        )
        actuator_ready = (
            self.state
            in {
                "AVOIDANCE_READY",
                "MOTION_COMMAND_PENDING",
                "MOTION_ACTIVE",
                "STOP_ACTIVE",
                "RELEASING_CONTROL",
                "RELEASE_FINAL_ATTEMPT",
            }
            and (
                physical_ready
                or (self.failsafe_stop_takeover and safe_stop_ready)
            )
        ) or (
            self.state
            in {
                "CLEAR_HOLD",
                "NEUTRALIZING",
                "SAFE_NEUTRAL_WAIT_CLEAR",
                "RELEASE_FINAL_NEUTRAL",
            }
            and safe_stop_ready
        )
        if self.failsafe_stop_takeover and self.state in {
            "TAKEOVER_REQUESTED",
            "WAITING_FOR_MANUAL_CONFIRMATION",
            "AVOIDANCE_READY",
            "MOTION_COMMAND_PENDING",
            "STOP_ACTIVE",
            "SAFE_NEUTRAL_WAIT_CLEAR",
            "CLEAR_HOLD",
            "NEUTRALIZING",
            "RELEASE_FINAL_NEUTRAL",
        }:
            hardware_command = "STOP"
        elif self.state in {"MOTION_COMMAND_PENDING", "MOTION_ACTIVE"}:
            hardware_command = self.last_hazard_command
        elif self.state in {
            "STOP_ACTIVE",
            "CLEAR_HOLD",
            "NEUTRALIZING",
            "SAFE_NEUTRAL_WAIT_CLEAR",
            "RELEASE_FINAL_NEUTRAL",
            "AUTO_RESTORE_REQUESTED",
            "WAITING_FOR_AUTO_CONFIRMATION",
            "AUTO_RESTORE_RETRY",
            "SAFE_MANUAL_WAIT_AUTO",
            "AUTO_REJOIN_VERIFY",
        }:
            hardware_command = "STOP"
        else:
            hardware_command = "HOLD_COURSE"
        return AutoTakeoverOutput(
            state=self.state,
            hardware_command=hardware_command,
            command_publish_allowed=command_publish_allowed,
            motion_allowed=motion_allowed,
            actuator_path_ready=actuator_ready,
            physical_ready=physical_ready,
            requested_mode=self.requested_mode,
            mode_request_sent=self.mode_request_sent,
            mode_request_acknowledged=self.mode_request_acknowledged,
            blocked_reason=self.blocked_reason,
            abort_reason=self.abort_reason,
        )

    def status(self, data: AutoTakeoverInputs) -> dict[str, Any]:
        now = max(0.0, float(data.now))
        result = asdict(self.output(data))
        result.update(
            {
                "cycle_id": self.cycle_id,
                "completed_cycle_count": self.completed_cycle_count,
                "cycle_takeover_started_at": self.cycle_takeover_started_at,
                "cycle_elapsed_s": self._duration(
                    now, self.cycle_takeover_started_at
                ),
                "original_mode": self.original_mode,
                "takeover_owner": self.takeover_owner,
                "manual_requested_by_ca": self.manual_requested_by_ca,
                "control_ever_owned": self.control_ever_owned,
                "motion_ever_sent": self.motion_ever_sent,
                "restore_auto_allowed": self.restore_auto_allowed,
                "failsafe_stop_takeover": self.failsafe_stop_takeover,
                "failsafe_stop_reason": self.failsafe_stop_reason,
                "operational_reason": self._operational_reason(data),
                "manager_fresh": data.manager_fresh,
                "watchdog_fresh": data.watchdog_fresh,
                "perception_state": data.perception_state,
                "camera_perception_available": (
                    data.camera_perception_available
                ),
                "first_hazard_time": self.first_hazard_at,
                "manual_request_time": (
                    self.manual_requested_at
                ),
                "manual_confirmed_time": self.manual_confirmed_at,
                "motion_start_time": self.motion_started_at,
                "motion_pending_time": self.motion_pending_at,
                "motion_delivery_confirmed_time": (
                    self.motion_delivery_confirmed_at
                ),
                "motion_delivery_evidence": self.motion_delivery_evidence,
                "motion_watchdog_age_s": max(
                    0.0, float(data.command_delivery_age_s)
                ),
                "command_delivery_fresh": data.command_delivery_fresh,
                "command_freshness_watchdog_s": (
                    self.command_freshness_watchdog_s
                ),
                "motion_delivery_timeout_s": self.motion_delivery_timeout_s,
                "motion_limit_reached": self.motion_limit_reached,
                "motion_limit_reached_time": self.motion_limit_reached_at,
                "clear_start_time": self.clear_started_at,
                "clear_hold_completed": self.clear_hold_completed,
                "neutralizing_started_at": self.neutralizing_started_at,
                "clear_elapsed_s": (
                    self._duration(now, self.clear_started_at)
                    if self.state == "CLEAR_HOLD"
                    else 0.0
                ),
                "release_start_time": self.release_started_at,
                "release_final_attempted_time": (
                    self.release_final_attempted_at
                ),
                "release_timeout_s": self.release_timeout_s,
                "release_echo_received": data.release_echo_received,
                "auto_confirmed_time": self.auto_confirmed_at,
                "auto_request_time": self.auto_requested_at,
                "auto_request_count": (
                    self.mode_request_count
                    if self.requested_mode == "AUTO"
                    else 0
                ),
                "auto_service_response": self.auto_service_response,
                "auto_mode_observed": self.auto_mode_observed,
                "auto_restore_pending": self.auto_restore_pending,
                "auto_rejoin_started_at": self.auto_rejoin_started_at,
                "auto_rejoin_verified": self.auto_rejoin_verified,
                "mode_retry_interval_s": self.mode_retry_interval_s,
                "auto_rejoin_verify_s": self.auto_rejoin_verify_s,
                "rc_neutral_confirmed": data.rc_neutral_confirmed,
                "mission_status_known": data.mission_status_known,
                "mission_active": data.mission_active,
                "hazard_to_manual_request": self._duration(
                    self.manual_requested_at, self.first_hazard_at
                ),
                "manual_request_to_manual_confirm": self._duration(
                    self.manual_confirmed_at, self.manual_requested_at
                ),
                "total_takeover_duration": self._duration(
                    self.auto_confirmed_at,
                    self.cycle_takeover_started_at,
                ),
                "maximum_takeover_duration_s": self.maximum_takeover_duration_s,
                "session_mode_request_count": self.session_mode_request_count,
                "last_event": self.last_event,
            }
        )
        return result
