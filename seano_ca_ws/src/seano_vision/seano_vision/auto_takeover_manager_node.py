#!/usr/bin/env python3
"""Sole `/mavros/set_mode` owner for the guarded AUTO takeover runtime."""

from __future__ import annotations

import json
from pathlib import Path
import time

from mavros_msgs.msg import (
    OverrideRCIn,
    State,
    WaypointList,
    WaypointReached,
)
from mavros_msgs.srv import SetMode
import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, Float32, String

from .auto_takeover_state import (
    AutoTakeoverCore,
    AutoTakeoverInputs,
    RcCycleEvidence,
    classify_slow_effectiveness,
)
from .thruster_test_safety import TestLimits, canonical_thruster_mapping


class AutoTakeoverManager(Node):
    def __init__(self) -> None:
        super().__init__("auto_takeover_manager_node")
        defaults = (
            ("enabled", False),
            ("operator_confirmed", False),
            ("mode_takeover_confirmed", False),
            ("startup_grace_s", 8.0),
            ("hazard_debounce_s", 0.4),
            ("clear_hold_s", 2.5),
            ("mode_timeout_s", 3.0),
            ("maximum_motion_duration_s", 2.0),
            ("maximum_takeover_duration_s", 15.0),
            ("command_freshness_watchdog_s", 2.0),
            ("motion_delivery_timeout_s", 0.75),
            ("release_timeout_s", 1.0),
            ("final_release_timeout_s", 0.5),
            ("maximum_mode_requests", 3),
            ("mode_retry_interval_s", 1.0),
            ("auto_rejoin_verify_s", 0.5),
            ("web_video_available", False),
            ("heartbeat_timeout_s", 0.5),
            ("command_timeout_s", 0.3),
            ("mapping_profile", "SEAPORTAL_ACTUAL"),
            ("steering_channel_index", 0),
            ("throttle_channel_index", 2),
            ("pwm_min", 1000),
            ("neutral_throttle_pwm", 1500),
            ("pwm_max", 2000),
            ("cruise_reference_throttle_percent", 100.0),
            ("slow_factor", 0.58),
            ("slow_throttle_percent", 58.0),
            ("minimum_effective_throttle_percent", 58.0),
            ("turn_throttle_percent", 0.0),
            ("maximum_test_throttle_percent", 58.0),
            ("maximum_steering_percent", 100.0),
            ("log_dir", ""),
            ("session_id", ""),
        )
        for name, value in defaults:
            self.declare_parameter(name, value)
        if not all(
            bool(self._p(name))
            for name in ("enabled", "operator_confirmed", "mode_takeover_confirmed")
        ):
            raise RuntimeError("AUTO_TAKEOVER_STATIC_GATE_CLOSED")
        self._validate_throttle_calibration()

        started = time.monotonic()
        self.core = AutoTakeoverCore(
            started_at=started,
            startup_grace_s=float(self._p("startup_grace_s")),
            hazard_debounce_s=float(self._p("hazard_debounce_s")),
            clear_hold_s=float(self._p("clear_hold_s")),
            mode_timeout_s=float(self._p("mode_timeout_s")),
            maximum_motion_duration_s=float(self._p("maximum_motion_duration_s")),
            maximum_takeover_duration_s=float(
                self._p("maximum_takeover_duration_s")
            ),
            command_freshness_watchdog_s=float(
                self._p("command_freshness_watchdog_s")
            ),
            motion_delivery_timeout_s=float(
                self._p("motion_delivery_timeout_s")
            ),
            release_timeout_s=float(self._p("release_timeout_s")),
            final_release_timeout_s=float(
                self._p("final_release_timeout_s")
            ),
            maximum_mode_requests=int(self._p("maximum_mode_requests")),
            mode_retry_interval_s=float(
                self._p("mode_retry_interval_s")
            ),
            auto_rejoin_verify_s=float(
                self._p("auto_rejoin_verify_s")
            ),
        )
        self.fcu_connected = self.fcu_armed = False
        self.fcu_mode = "UNKNOWN"
        self.desired_command = self.safe_command = self.selected_command = "STALE"
        self.command_at = self.ca_mode_at = self.failsafe_at = 0.0
        self.ca_mode = "LOST_PERCEPTION"
        self.failsafe = True
        self.mqtt_connected = False
        self.adapter_at = self.hud_at = 0.0
        self.adapter_abort_reason = ""
        self.foreign = False
        self.neutral_seen = self.release_seen = self.motion_seen = False
        self.motion_sent_at = self.neutral_sent_at = self.release_sent_at = 0.0
        self.throttle = self.steering = 0.0
        self.mapped_command = "HOLD_COURSE"
        self.mqtt_ack_seen = self.own_echo_seen = False
        self.release_echo_seen = False
        self.adapter_control_acquired = False
        self.mqtt_ack_at = self.own_echo_at = self.rc_delivery_at = 0.0
        self.rc_observed = False
        self.mission_status_known = False
        self.mission_active = True
        self.mission_last_seq = -1
        self.mission_reached_seq = -1
        self.last_rc_channels = None
        self.rc_cycle = RcCycleEvidence(
            steering_channel_index=int(
                self._p("steering_channel_index")
            ),
            throttle_channel_index=int(
                self._p("throttle_channel_index")
            ),
            pwm_min=int(self._p("pwm_min")),
            neutral_throttle_pwm=int(self._p("neutral_throttle_pwm")),
            pwm_max=int(self._p("pwm_max")),
        )
        self.mapping_limits = TestLimits(
            mapping_profile=str(self._p("mapping_profile")),
            maximum_throttle_percent=float(
                self._p("maximum_test_throttle_percent")
            ),
            maximum_allowed_throttle_percent=58.0,
            cruise_reference_throttle_percent=float(
                self._p("cruise_reference_throttle_percent")
            ),
            slow_factor=float(self._p("slow_factor")),
            slow_throttle_percent=float(self._p("slow_throttle_percent")),
            minimum_effective_throttle_percent=float(
                self._p("minimum_effective_throttle_percent")
            ),
            turn_throttle_percent=float(
                self._p("turn_throttle_percent")
            ),
            maximum_steering_percent=float(
                self._p("maximum_steering_percent")
            ),
            maximum_allowed_steering_percent=100.0,
            steering_channel_index=int(
                self._p("steering_channel_index")
            ),
            throttle_channel_index=int(
                self._p("throttle_channel_index")
            ),
            pwm_min=int(self._p("pwm_min")),
            neutral_throttle_pwm=int(self._p("neutral_throttle_pwm")),
            pwm_max=int(self._p("pwm_max")),
        )
        self.last_state = ""
        self.release_logged = False
        self.log_paths = self._prepare_logs(str(self._p("log_dir")))

        self.create_subscription(State, "/mavros/state", self._fcu, 10)
        self.create_subscription(String, "/ca/command", self._desired, 10)
        self.create_subscription(String, "/ca/command_safe", self._safe, 10)
        self.create_subscription(String, "/ca/mode", self._mode, 10)
        self.create_subscription(Bool, "/ca/failsafe_active", self._failsafe, 10)
        self.create_subscription(
            Float32, "/ca/hardware_test/heartbeat", self._adapter_heartbeat, 10
        )
        self.create_subscription(
            Float32, "/ca/auto_takeover/hud_heartbeat", self._hud_heartbeat, 10
        )
        self.create_subscription(
            Bool, "/ca/hardware_test/mqtt_connected", self._mqtt, 10
        )
        self.create_subscription(
            Bool, "/ca/hardware_test/foreign_command_detected", self._foreign, 10
        )
        self.create_subscription(
            String,
            "/ca/hardware_test/adapter_abort_reason",
            self._adapter_abort,
            10,
        )
        self.create_subscription(
            Bool, "/ca/hardware_test/neutral_sent", self._neutral, 10
        )
        self.create_subscription(
            Bool, "/ca/hardware_test/release_sent", self._release, 10
        )
        self.create_subscription(
            Bool, "/ca/hardware_test/motion_command_sent", self._motion, 10
        )
        self.create_subscription(
            Bool, "/ca/hardware_test/mqtt_ack_received", self._mqtt_ack, 10
        )
        self.create_subscription(
            Bool,
            "/ca/hardware_test/mqtt_own_echo_received",
            self._own_echo,
            10,
        )
        self.create_subscription(
            Bool,
            "/ca/hardware_test/release_own_echo_received",
            self._release_echo,
            10,
        )
        self.create_subscription(
            Bool,
            "/ca/hardware_test/control_acquired",
            self._control_acquired,
            10,
        )
        self.create_subscription(
            String,
            "/ca/hardware_test/mapped_command",
            self._mapped_command,
            10,
        )
        self.create_subscription(
            Float32, "/ca/hardware_test/throttle", self._throttle, 10
        )
        self.create_subscription(
            Float32, "/ca/hardware_test/steering", self._steering, 10
        )
        self.create_subscription(
            OverrideRCIn, "/mavros/rc/override", self._rc_override, 10
        )
        self.create_subscription(
            WaypointList,
            "/mavros/mission/waypoints",
            self._mission_waypoints,
            10,
        )
        self.create_subscription(
            WaypointReached,
            "/mavros/mission/reached",
            self._mission_reached,
            10,
        )

        self.pub_status = self.create_publisher(
            String, "/ca/auto_takeover/status_json", 10
        )
        self.pub_state = self.create_publisher(String, "/ca/auto_takeover/state", 10)
        self.pub_hardware_command = self.create_publisher(
            String, "/ca/auto_takeover/hardware_command", 10
        )
        self.pub_motion = self.create_publisher(
            Bool, "/ca/hardware_test/motion_allowed", 10
        )
        self.pub_command_publish = self.create_publisher(
            Bool, "/ca/hardware_test/command_publish_allowed", 10
        )
        self.pub_path = self.create_publisher(Bool, "/ca/actuator_path_ready", 10)
        self.pub_heartbeat = self.create_publisher(
            Float32, "/ca/hardware_test/guardian_heartbeat", 10
        )
        self.cli_mode = self.create_client(SetMode, "/mavros/set_mode")
        self.create_timer(0.05, self._tick)

    def _p(self, name):
        return self.get_parameter(name).value

    def _validate_throttle_calibration(self) -> None:
        neutral = int(self._p("neutral_throttle_pwm"))
        limits = TestLimits(
            mapping_profile=str(self._p("mapping_profile")),
            maximum_throttle_percent=float(
                self._p("maximum_test_throttle_percent")
            ),
            maximum_allowed_throttle_percent=58.0,
            cruise_reference_throttle_percent=float(
                self._p("cruise_reference_throttle_percent")
            ),
            slow_factor=float(self._p("slow_factor")),
            slow_throttle_percent=float(self._p("slow_throttle_percent")),
            minimum_effective_throttle_percent=float(
                self._p("minimum_effective_throttle_percent")
            ),
            turn_throttle_percent=float(
                self._p("turn_throttle_percent")
            ),
            maximum_steering_percent=float(
                self._p("maximum_steering_percent")
            ),
            maximum_allowed_steering_percent=100.0,
            steering_channel_index=int(
                self._p("steering_channel_index")
            ),
            throttle_channel_index=int(
                self._p("throttle_channel_index")
            ),
            pwm_min=int(self._p("pwm_min")),
            neutral_throttle_pwm=neutral,
            pwm_max=int(self._p("pwm_max")),
        )
        valid, reason = limits.validate_first_test()
        if not 800 <= neutral <= 2200 or not valid:
            raise RuntimeError(
                reason
                if reason == "SLOW_THROTTLE_BELOW_EFFECTIVE_THRESHOLD"
                else "AUTO_TAKEOVER_THROTTLE_CALIBRATION_INVALID"
            )

    @staticmethod
    def _prepare_logs(log_dir: str) -> dict[str, Path]:
        path = Path(log_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return {
            "mode": path / "mode_manager_events.jsonl",
            "guardian": path / "guardian_events.jsonl",
            "rc": path / "rc_evidence.jsonl",
        }

    def _log(self, target: str, event: str, **data) -> None:
        record = {
            "timestamp": time.time(),
            "event": event,
            "session_id": str(self._p("session_id")),
            "cycle_id": self.core.cycle_id,
            **data,
        }
        with self.log_paths[target].open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")

    def _fcu(self, msg): self.fcu_connected = bool(msg.connected); self.fcu_armed = bool(msg.armed); self.fcu_mode = str(msg.mode)
    def _desired(self, msg): self.desired_command = str(msg.data)
    def _safe(self, msg): self.safe_command = self.selected_command = str(msg.data); self.command_at = time.monotonic()
    def _mode(self, msg): self.ca_mode = str(msg.data); self.ca_mode_at = time.monotonic()
    def _failsafe(self, msg): self.failsafe = bool(msg.data); self.failsafe_at = time.monotonic()
    def _adapter_heartbeat(self, msg): self.adapter_at = time.monotonic()
    def _hud_heartbeat(self, msg): self.hud_at = time.monotonic()
    def _mqtt(self, msg): self.mqtt_connected = bool(msg.data)
    def _foreign(self, msg): self.foreign = bool(msg.data)
    def _adapter_abort(self, msg): self.adapter_abort_reason = str(msg.data)
    def _neutral(self, msg):
        if bool(msg.data) and not self.neutral_seen:
            self.neutral_sent_at = time.monotonic()
        self.neutral_seen |= bool(msg.data)
    def _release(self, msg):
        if bool(msg.data) and not self.release_seen:
            self.release_sent_at = time.monotonic()
        if bool(msg.data) and not self.release_logged:
            self._log("guardian", "RELEASE_SENT", state=self.core.state)
            self.release_logged = True
        self.release_seen |= bool(msg.data)
    def _motion(self, msg):
        if bool(msg.data):
            self.motion_sent_at = time.monotonic()
        self.motion_seen |= bool(msg.data)
    def _mqtt_ack(self, msg):
        if bool(msg.data):
            self.mqtt_ack_at = time.monotonic()
            self.mqtt_ack_seen = True
    def _own_echo(self, msg):
        if bool(msg.data):
            self.own_echo_at = time.monotonic()
            self.own_echo_seen = True
    def _release_echo(self, msg):
        self.release_echo_seen |= bool(msg.data)
    def _control_acquired(self, msg):
        self.adapter_control_acquired = bool(msg.data)
    def _mapped_command(self, msg):
        self.mapped_command = str(msg.data)
    def _throttle(self, msg): self.throttle = float(msg.data)
    def _steering(self, msg): self.steering = float(msg.data)

    def _mission_waypoints(self, msg: WaypointList) -> None:
        waypoint_count = len(msg.waypoints)
        self.mission_status_known = waypoint_count > 0
        self.mission_last_seq = waypoint_count - 1
        if self.mission_status_known:
            self.mission_active = (
                self.mission_reached_seq < self.mission_last_seq
            )

    def _mission_reached(self, msg: WaypointReached) -> None:
        self.mission_reached_seq = int(msg.wp_seq)
        if self.mission_status_known:
            self.mission_active = (
                self.mission_reached_seq < self.mission_last_seq
            )

    @staticmethod
    def _full_name(info) -> str:
        namespace = str(info.node_namespace or "/")
        name = str(info.node_name).lstrip("/")
        return f"/{name}" if namespace == "/" else f"{namespace.rstrip('/')}/{name}"

    def _rc_graph(self) -> tuple[int, str, bool]:
        publishers = self.get_publishers_info_by_topic("/mavros/rc/override")
        subscribers = self.get_subscriptions_info_by_topic("/mavros/rc/override")
        publisher = self._full_name(publishers[0]) if len(publishers) == 1 else ""
        mavros_rc = any(self._full_name(info) == "/mavros/rc" for info in subscribers)
        return len(publishers), publisher, mavros_rc

    def _rc_override(self, msg: OverrideRCIn) -> None:
        channels = [int(value) for value in msg.channels]
        self.last_rc_channels = channels
        if (
            self.rc_cycle.pre_motion_channels is None
            and self.core.state == "AVOIDANCE_READY"
        ):
            self.rc_cycle.capture_pre_motion(channels)
        evidence = self.rc_cycle.observe(
            channels,
            requested_throttle=self.throttle,
            requested_steering=self.steering,
            motion_expected=(
                self.motion_seen
                or self.core.state
                in {
                    "MOTION_COMMAND_PENDING",
                    "MOTION_ACTIVE",
                    "STOP_ACTIVE",
                    "SAFE_NEUTRAL_WAIT_CLEAR",
                }
            ),
        )
        if evidence.get("current_rc_matches_requested_command"):
            self.rc_delivery_at = time.monotonic()
        self.rc_observed = bool(evidence["rc_changed_from_pre_motion"])
        if (
            not self.motion_seen
            and self.core.state
            not in {
                "MOTION_COMMAND_PENDING",
                "STOP_ACTIVE",
                "SAFE_NEUTRAL_WAIT_CLEAR",
            }
            and not evidence["neutral_observed"]
        ):
            return
        self._log(
            "rc",
            "RC_OVERRIDE_OBSERVED",
            hardware_command=self.core.last_hazard_command,
            throttle=self.throttle,
            steering=self.steering,
            channels=channels,
            **evidence,
        )

    def _reset_cycle_runtime(self, cycle_id: int) -> None:
        self.neutral_seen = self.release_seen = self.motion_seen = False
        self.neutral_sent_at = self.release_sent_at = self.motion_sent_at = 0.0
        self.release_logged = False
        self.throttle = self.steering = 0.0
        self.mapped_command = "HOLD_COURSE"
        self.mqtt_ack_seen = self.own_echo_seen = False
        self.release_echo_seen = False
        self.adapter_control_acquired = False
        self.mqtt_ack_at = self.own_echo_at = self.rc_delivery_at = 0.0
        self.rc_observed = False
        self.rc_cycle.reset(cycle_id)

    def _reset_delivery_evidence(self) -> None:
        self.motion_seen = False
        self.motion_sent_at = 0.0
        self.mqtt_ack_seen = self.own_echo_seen = False
        self.mqtt_ack_at = self.own_echo_at = self.rc_delivery_at = 0.0
        self.rc_observed = False
        self.rc_cycle.reset_delivery()

    def _request_mode(self, mode: str) -> None:
        now = time.time()
        event = (
            "AUTO_RESTORE_REQUEST_SENT"
            if mode == "AUTO"
            else f"{mode}_REQUESTED"
        )
        self._log("mode", event, requested_mode=mode)
        if not self.cli_mode.service_is_ready():
            self.core.report_mode_service_unavailable(mode)
            self._log("mode", "MODE_SERVICE_UNAVAILABLE", requested_mode=mode)
            return
        request = SetMode.Request()
        request.base_mode = 0
        request.custom_mode = mode
        future = self.cli_mode.call_async(request)

        def completed(result_future):
            try:
                response = result_future.result()
                accepted = bool(response.mode_sent)
            except Exception:
                accepted = False
            self.core.report_mode_request(mode, accepted)
            response_event = (
                "AUTO_RESTORE_SERVICE_RESPONSE"
                if mode == "AUTO"
                else "MODE_SERVICE_RESPONSE"
            )
            self._log(
                "mode",
                response_event,
                requested_mode=mode,
                accepted=accepted,
            )

        future.add_done_callback(completed)

    def _inputs(self, now: float) -> AutoTakeoverInputs:
        heartbeat_timeout = float(self._p("heartbeat_timeout_s"))
        command_timeout = float(self._p("command_timeout_s"))
        command_fresh = self.command_at > 0.0 and now - self.command_at <= command_timeout
        manager_fresh = (
            self.ca_mode_at > 0.0
            and now - self.ca_mode_at <= heartbeat_timeout
        )
        perception_state = self.ca_mode.strip().upper()
        camera_perception_available = bool(
            manager_fresh and perception_state != "LOST_PERCEPTION"
        )
        perception_valid = camera_perception_available
        adapter_fresh = self.adapter_at > 0.0 and now - self.adapter_at <= heartbeat_timeout
        hud_fresh = self.hud_at > 0.0 and now - self.hud_at <= heartbeat_timeout
        failsafe_fresh = self.failsafe_at > 0.0 and now - self.failsafe_at <= heartbeat_timeout
        last_delivery_at = max(
            self.motion_sent_at,
            self.mqtt_ack_at,
            self.own_echo_at,
            self.rc_delivery_at,
        )
        delivery_age = (
            max(0.0, now - last_delivery_at)
            if last_delivery_at > 0.0
            else self.core.command_freshness_watchdog_s + 1.0
        )
        delivery_fresh = bool(
            last_delivery_at > 0.0
            and delivery_age <= self.core.command_freshness_watchdog_s
        )
        rc_count, rc_name, rc_subscriber = self._rc_graph()
        risk_policy_valid = (
            self.selected_command.strip().upper() != "STALE"
        )
        software_ready = (
            command_fresh
            and perception_valid
            and failsafe_fresh
            and adapter_fresh
            and hud_fresh
            and risk_policy_valid
            and self.mqtt_connected
            and bool(self._p("web_video_available"))
        )
        abort = self.adapter_abort_reason.upper()
        return AutoTakeoverInputs(
            now=now,
            fcu_connected=self.fcu_connected,
            fcu_armed=self.fcu_armed,
            fcu_mode=self.fcu_mode,
            software_ready=software_ready,
            perception_valid=perception_valid,
            perception_state=perception_state,
            camera_perception_available=camera_perception_available,
            manager_fresh=manager_fresh,
            watchdog_fresh=failsafe_fresh,
            risk_policy_valid=risk_policy_valid,
            command_fresh=command_fresh,
            failsafe_active=self.failsafe or not failsafe_fresh,
            desired_command=self.desired_command,
            safe_command=self.safe_command,
            selected_command=self.selected_command,
            mqtt_connected=self.mqtt_connected,
            web_video_available=bool(self._p("web_video_available")),
            adapter_fresh=adapter_fresh,
            hud_fresh=hud_fresh,
            rc_publisher_count=rc_count,
            rc_publisher_name=rc_name,
            rc_subscriber_present=rc_subscriber,
            foreign_active=self.foreign and "ACTIVE" in abort,
            foreign_unknown=self.foreign and "UNKNOWN" in abort,
            retained_foreign=self.foreign and "RETAINED" in abort,
            neutral_sent=self.neutral_seen,
            release_sent=self.release_seen,
            release_echo_received=self.release_echo_seen,
            motion_sent=self.motion_seen,
            motion_command_sent=self.motion_seen,
            mqtt_ack_received=self.mqtt_ack_seen,
            own_echo_received=self.own_echo_seen,
            rc_command_delivered=self.rc_cycle.rc_command_delivered,
            rc_neutral_confirmed=self.rc_cycle.neutral_observed,
            command_delivery_fresh=delivery_fresh,
            command_delivery_age_s=delivery_age,
            adapter_control_acquired=self.adapter_control_acquired,
            adapter_fault_reason=(
                "" if self.foreign else self.adapter_abort_reason
            ),
            mission_status_known=self.mission_status_known,
            mission_active=self.mission_active,
        )

    def _tick(self) -> None:
        now = time.monotonic()
        data = self._inputs(now)
        output = self.core.step(data)
        mode_request = self.core.consume_mode_request()
        if mode_request:
            self._request_mode(mode_request)
        if output.state != self.last_state:
            previous_state = self.last_state
            if output.state == "TAKEOVER_REQUESTED":
                self._reset_cycle_runtime(self.core.cycle_id)
            elif output.state == "AVOIDANCE_READY":
                if previous_state in {
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
                }:
                    self._reset_delivery_evidence()
                    self.neutral_seen = self.release_seen = False
                    self.neutral_sent_at = self.release_sent_at = 0.0
                captured = (
                    self.rc_cycle.capture_pre_motion(
                        self.last_rc_channels
                    )
                    if self.rc_cycle.pre_motion_channels is None
                    else True
                )
                self._log(
                    "rc",
                    "RC_PRE_MOTION_BASELINE",
                    captured=captured,
                    **self.rc_cycle.status(),
                )
            elif output.state == "SAFE_NEUTRAL_WAIT_CLEAR":
                self._reset_delivery_evidence()
            elif output.state == "AUTO_CONFIRMED":
                self._log(
                    "rc",
                    "RC_CYCLE_SUMMARY",
                    **self.rc_cycle.status(),
                )
            elif (
                output.state == "AUTO_MISSION_MONITORING"
                and previous_state == "AUTO_CONFIRMED"
            ):
                self._reset_cycle_runtime(self.core.cycle_id)
            status = self.core.status(data)
            self._log("mode", "STATE_CHANGED", **status)
            self._log("guardian", "SAFETY_STATE_CHANGED", **status)
            self.last_state = output.state
        for event in self.core.consume_events():
            event_name = str(event.pop("event"))
            self._log("guardian", event_name, state=output.state, **event)
            if event_name.startswith("AUTO_") or event_name == "TOTAL_TAKEOVER_DURATION":
                self._log("mode", event_name, state=output.state, **event)
        status = self.core.status(data)
        mapped = canonical_thruster_mapping(
            output.hardware_command, self.mapping_limits
        )
        status.update(
            {
                "fcu_mode": self.fcu_mode,
                "fcu_armed": self.fcu_armed,
                "software_ready": data.software_ready,
                "mqtt_connected": self.mqtt_connected,
                "web_video_available": data.web_video_available,
                "rc_publisher": data.rc_publisher_name,
                "desired_command": self.desired_command,
                "safe_command": self.safe_command,
                "selected_command": self.selected_command,
                "mapped_command": mapped.command,
                "command_published": self.motion_seen,
                "mqtt_ack_received": self.mqtt_ack_seen,
                "mqtt_own_echo_received": self.own_echo_seen,
                "throttle": self.throttle,
                "steering": self.steering,
                "requested_throttle": mapped.throttle_percent,
                "requested_steering": mapped.steering_percent,
                "requested_steering_pwm": mapped.requested_steering_pwm,
                "requested_throttle_pwm": mapped.requested_throttle_pwm,
                "motion_command_sent": self.motion_seen,
                "motion_command_sent_time": self.motion_sent_at,
                "neutral_sent": self.neutral_seen,
                "neutral_sent_time": self.neutral_sent_at,
                "release_sent": self.release_seen,
                "release_own_echo_received": self.release_echo_seen,
                "release_sent_time": self.release_sent_at,
                "rc_override_observed": self.rc_observed,
                "auto_restore_requested": self.core.requested_mode == "AUTO",
                "auto_restore_confirmed": output.state == "AUTO_CONFIRMED",
                "mission_last_seq": self.mission_last_seq,
                "mission_reached_seq": self.mission_reached_seq,
                "session_id": str(self._p("session_id")),
                "takeover_limit_s": self.core.maximum_takeover_duration_s,
                "neutral_throttle_pwm": int(
                    self._p("neutral_throttle_pwm")
                ),
                "mapping_profile": str(self._p("mapping_profile")),
                "steering_channel_index": int(
                    self._p("steering_channel_index")
                ),
                "throttle_channel_index": int(
                    self._p("throttle_channel_index")
                ),
                "pwm_min": int(self._p("pwm_min")),
                "pwm_max": int(self._p("pwm_max")),
                "slow_throttle_percent": float(
                    self._p("slow_throttle_percent")
                ),
                "minimum_effective_throttle_percent": float(
                    self._p("minimum_effective_throttle_percent")
                ),
                "maximum_test_throttle_percent": float(
                    self._p("maximum_test_throttle_percent")
                ),
                "cruise_reference_throttle_percent": float(
                    self._p("cruise_reference_throttle_percent")
                ),
                "slow_factor": float(self._p("slow_factor")),
                "turn_throttle_percent": float(
                    self._p("turn_throttle_percent")
                ),
                "maximum_steering_percent": float(
                    self._p("maximum_steering_percent")
                ),
            }
        )
        status.update(self.rc_cycle.status())
        requested_slow_throttle = mapped.throttle_percent
        if self.core.last_hazard_command in {
            "SLOW_DOWN",
            "TURN_LEFT_SLOW",
            "TURN_RIGHT_SLOW",
        }:
            slow_effective, slow_status = classify_slow_effectiveness(
                requested_slow_throttle,
                float(self._p("minimum_effective_throttle_percent")),
            )
        else:
            slow_effective, slow_status = "UNKNOWN", "PHYSICAL_EFFECT_UNKNOWN"
        status["physical_thruster_effective"] = "UNKNOWN"
        status["physical_effect_status"] = "PHYSICAL_EFFECT_UNKNOWN"
        status["slow_effective"] = slow_effective
        status["slow_effectiveness_status"] = slow_status
        self.pub_status.publish(String(data=json.dumps(status, separators=(",", ":"), sort_keys=True)))
        self.pub_state.publish(String(data=output.state))
        self.pub_hardware_command.publish(String(data=output.hardware_command))
        self.pub_command_publish.publish(
            Bool(data=output.command_publish_allowed)
        )
        self.pub_motion.publish(Bool(data=output.motion_allowed))
        self.pub_path.publish(Bool(data=output.actuator_path_ready))
        self.pub_heartbeat.publish(Float32(data=float(now)))


def main(args=None) -> None:
    rclpy.init(args=args)
    node = AutoTakeoverManager()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
