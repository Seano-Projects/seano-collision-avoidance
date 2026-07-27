#!/usr/bin/env python3
"""Guarded shared-MQTT adapter used only by the explicit hardware-test run."""

from __future__ import annotations

import json
import math
from pathlib import Path
import queue
import threading
import time

import rclpy
from mavros_msgs.msg import OverrideRCIn
from rclpy.node import Node
from std_msgs.msg import Bool, Float32, String

from .risk_policy import normalize_command_details
from .thruster_test_mqtt import PahoSharedTopicTransport
from .thruster_test_safety import (
    ACTIVE_FOREIGN_COMMAND,
    AdapterCore,
    BENIGN_NEUTRAL,
    BENIGN_RELEASE,
    ClassifiedMqttMessage,
    OwnMessageRegistry,
    OWN_MQTT_ECHO,
    PublishAction,
    SHARED_TOPIC,
    TestLimits,
    UNKNOWN_SCHEMA,
    canonical_thruster_mapping,
    classify_mqtt_message,
    publish_action_tracked,
)


class GuardedThrusterTestAdapter(Node):
    def __init__(self) -> None:
        super().__init__("guarded_thruster_test_adapter_node")
        defaults = (
            ("hardware_test_enabled", False),
            ("mqtt_publish_enabled", False),
            ("operator_confirmed", False),
            ("shared_mqtt_test_confirmed", False),
            ("tether_confirmed", False),
            ("emergency_stop_confirmed", False),
            ("exclusive_test_window_confirmed", False),
            ("foreign_command_monitor_enabled", True),
            ("reverse_allowed", False),
            ("mapping_profile", "LEGACY_CONSERVATIVE"),
            ("maximum_throttle_percent", 10.0),
            ("maximum_allowed_throttle_percent", 10.0),
            ("cruise_reference_throttle_percent", 20.0),
            ("slow_factor", 0.5),
            ("slow_throttle_percent", 10.0),
            ("minimum_effective_throttle_percent", 10.0),
            ("turn_throttle_percent", 10.0),
            ("maximum_steering_percent", 15.0),
            ("maximum_allowed_steering_percent", 15.0),
            ("steering_channel_index", 0),
            ("throttle_channel_index", 2),
            ("pwm_min", 1000),
            ("neutral_throttle_pwm", 1500),
            ("pwm_max", 2000),
            ("command_timeout_s", 0.30),
            ("heartbeat_timeout_s", 0.50),
            ("maximum_motion_duration_s", 2.0),
            ("mqtt_qos", 1),
            ("mqtt_retain", False),
            ("mqtt_topic", SHARED_TOPIC),
            ("command_topic", "/ca/command_safe"),
            ("session_id", ""),
            ("log_dir", ""),
            ("rate_hz", 20.0),
            ("neutral_repetitions", 3),
            ("release_repetitions", 3),
            ("bounded_stop_neutral", False),
            ("hold_stop_on_failsafe", False),
            ("release_without_extra_neutral", False),
        )
        for name, value in defaults:
            self.declare_parameter(name, value)

        self.limits = TestLimits(
            mapping_profile=str(self._p("mapping_profile")),
            maximum_throttle_percent=float(self._p("maximum_throttle_percent")),
            maximum_allowed_throttle_percent=float(
                self._p("maximum_allowed_throttle_percent")
            ),
            cruise_reference_throttle_percent=float(
                self._p("cruise_reference_throttle_percent")
            ),
            slow_factor=float(self._p("slow_factor")),
            slow_throttle_percent=float(self._p("slow_throttle_percent")),
            minimum_effective_throttle_percent=float(
                self._p("minimum_effective_throttle_percent")
            ),
            turn_throttle_percent=float(self._p("turn_throttle_percent")),
            maximum_steering_percent=float(self._p("maximum_steering_percent")),
            maximum_allowed_steering_percent=float(
                self._p("maximum_allowed_steering_percent")
            ),
            steering_channel_index=int(self._p("steering_channel_index")),
            throttle_channel_index=int(self._p("throttle_channel_index")),
            pwm_min=int(self._p("pwm_min")),
            neutral_throttle_pwm=int(self._p("neutral_throttle_pwm")),
            pwm_max=int(self._p("pwm_max")),
            command_timeout_s=float(self._p("command_timeout_s")),
            heartbeat_timeout_s=float(self._p("heartbeat_timeout_s")),
            maximum_motion_duration_s=float(self._p("maximum_motion_duration_s")),
            reverse_allowed=bool(self._p("reverse_allowed")),
            mqtt_qos=int(self._p("mqtt_qos")),
            mqtt_retain=bool(self._p("mqtt_retain")),
        )
        valid, reason = self.limits.validate_first_test()
        session_id = str(self._p("session_id"))
        self.core = AdapterCore(
            limits=self.limits,
            session_id=session_id or None,
            neutral_repetitions=int(self._p("neutral_repetitions")),
            release_repetitions=int(self._p("release_repetitions")),
            bounded_stop_neutral=bool(self._p("bounded_stop_neutral")),
            release_without_extra_neutral=bool(
                self._p("release_without_extra_neutral")
            ),
        )
        self.hold_stop_on_failsafe = bool(
            self._p("hold_stop_on_failsafe")
        )
        self.topic = str(self._p("mqtt_topic"))
        self.left = self.right = 0.0
        self.command = "STALE"
        self.command_t = 0.0
        self.failsafe = True
        self.actuator_path_ready = False
        self.motion_allowed = False
        self.command_publish_allowed = False
        self.guardian_heartbeat_t = 0.0
        self.preview_throttle = self.preview_steering = 0.0
        self.foreign_detected = False
        self.abort_reason = "" if valid else reason
        self.mqtt_connected = False
        self.pending_messages: queue.Queue[ClassifiedMqttMessage] = queue.Queue()
        self.acknowledged_mids: queue.Queue[int] = queue.Queue()
        self.own_messages = OwnMessageRegistry(
            pending_ttl_s=5.0,
            completed_grace_s=1.0,
        )
        self.transport = None
        self.transport_lock = threading.Lock()
        self.last_request_signature = None
        self.motion_command_sent = False
        self.mqtt_ack_received = False
        self.own_echo_received = False
        self.release_echo_received = False
        self.last_publish_monotonic = 0.0
        self.last_publish_sequence = 0
        self.last_rc_channels = None
        self.log_path = self._prepare_log_path(str(self._p("log_dir")))

        self.create_subscription(Float32, "/seano/left_cmd", self._left, 10)
        self.create_subscription(Float32, "/seano/right_cmd", self._right, 10)
        self.create_subscription(
            String, str(self._p("command_topic")), self._command, 10
        )
        self.create_subscription(Bool, "/ca/failsafe_active", self._failsafe, 10)
        self.create_subscription(Bool, "/ca/actuator_path_ready", self._path_ready, 10)
        self.create_subscription(Float32, "/ca/thruster_preview/throttle", self._preview_throttle, 10)
        self.create_subscription(Float32, "/ca/thruster_preview/steering", self._preview_steering, 10)
        self.create_subscription(Bool, "/ca/hardware_test/motion_allowed", self._motion_allowed, 10)
        self.create_subscription(
            Bool,
            "/ca/hardware_test/command_publish_allowed",
            self._command_publish_allowed,
            10,
        )
        self.create_subscription(Float32, "/ca/hardware_test/guardian_heartbeat", self._guardian_heartbeat, 10)
        self.create_subscription(OverrideRCIn, "/mavros/rc/override", self._rc_override, 10)

        self.pub_session = self.create_publisher(String, "/ca/hardware_test/session_id", 10)
        self.pub_command = self.create_publisher(String, "/ca/hardware_test/command", 10)
        self.pub_throttle = self.create_publisher(Float32, "/ca/hardware_test/throttle", 10)
        self.pub_steering = self.create_publisher(Float32, "/ca/hardware_test/steering", 10)
        self.pub_heartbeat = self.create_publisher(Float32, "/ca/hardware_test/heartbeat", 10)
        self.pub_mqtt_connected = self.create_publisher(Bool, "/ca/hardware_test/mqtt_connected", 10)
        self.pub_mqtt_enabled = self.create_publisher(Bool, "/ca/hardware_test/mqtt_publish_enabled", 10)
        self.pub_foreign = self.create_publisher(Bool, "/ca/hardware_test/foreign_command_detected", 10)
        self.pub_abort = self.create_publisher(String, "/ca/hardware_test/adapter_abort_reason", 10)
        self.pub_neutral = self.create_publisher(Bool, "/ca/hardware_test/neutral_sent", 10)
        self.pub_release = self.create_publisher(Bool, "/ca/hardware_test/release_sent", 10)
        self.pub_motion_sent = self.create_publisher(
            Bool, "/ca/hardware_test/motion_command_sent", 10
        )
        self.pub_mqtt_ack = self.create_publisher(
            Bool, "/ca/hardware_test/mqtt_ack_received", 10
        )
        self.pub_own_echo = self.create_publisher(
            Bool, "/ca/hardware_test/mqtt_own_echo_received", 10
        )
        self.pub_release_echo = self.create_publisher(
            Bool,
            "/ca/hardware_test/release_own_echo_received",
            10,
        )
        self.pub_control_acquired = self.create_publisher(
            Bool, "/ca/hardware_test/control_acquired", 10
        )
        self.pub_mapped_command = self.create_publisher(
            String, "/ca/hardware_test/mapped_command", 10
        )

        static_enabled = all(bool(self._p(name)) for name in (
            "hardware_test_enabled", "mqtt_publish_enabled", "operator_confirmed",
            "shared_mqtt_test_confirmed", "tether_confirmed",
            "emergency_stop_confirmed", "exclusive_test_window_confirmed",
            "foreign_command_monitor_enabled",
        ))
        if valid and static_enabled and not self.limits.mqtt_retain:
            try:
                self.transport = PahoSharedTopicTransport(
                    client_id=f"ca-test-{self.core.session_id[:12]}",
                    topic=self.topic,
                    qos=self.limits.mqtt_qos,
                    on_message=self._mqtt_message_received,
                    on_connection=self._connection_changed,
                    on_ack=self.acknowledged_mids.put,
                )
                self.transport.start()
            except Exception as exc:
                self.abort_reason = f"MQTT_INIT_FAILED:{type(exc).__name__}"
                self.get_logger().error(self.abort_reason)
        else:
            self.abort_reason = self.abort_reason or "STATIC_GATE_CLOSED"
            self.get_logger().error(f"Adapter remains disconnected: {self.abort_reason}")

        hz = max(2.0, float(self._p("rate_hz")))
        self.create_timer(1.0 / hz, self._tick)
        self.get_logger().warn(
            "GUARDED hardware-test adapter loaded; MQTT motion remains guardian-gated."
        )

    def _p(self, name):
        return self.get_parameter(name).value

    def _prepare_log_path(self, log_dir: str) -> Path | None:
        if not log_dir:
            return None
        path = Path(log_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path / "adapter_events.jsonl"

    def _log(self, event: str, **data) -> None:
        if self.log_path is None:
            return
        record = {
            "timestamp": time.time(),
            "event": event,
            "local_session_id": self.core.session_id,
        }
        if "session_id" not in data:
            record["session_id"] = self.core.session_id
        record.update(data)
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")

    def _left(self, msg): self.left = float(msg.data)
    def _right(self, msg): self.right = float(msg.data)
    def _command(self, msg): self.command, _, _ = normalize_command_details(msg.data); self.command_t = time.monotonic()
    def _failsafe(self, msg): self.failsafe = bool(msg.data)
    def _path_ready(self, msg): self.actuator_path_ready = bool(msg.data)
    def _preview_throttle(self, msg): self.preview_throttle = float(msg.data)
    def _preview_steering(self, msg): self.preview_steering = float(msg.data)
    def _motion_allowed(self, msg): self.motion_allowed = bool(msg.data)
    def _command_publish_allowed(self, msg):
        self.command_publish_allowed = bool(msg.data)
    def _guardian_heartbeat(self, msg): self.guardian_heartbeat_t = time.monotonic()

    def _rc_override(self, msg: OverrideRCIn) -> None:
        if self.last_publish_monotonic <= 0.0:
            return
        age_s = time.monotonic() - self.last_publish_monotonic
        if age_s > 1.0:
            return
        channels = [int(value) for value in msg.channels]
        if channels == self.last_rc_channels:
            return
        self.last_rc_channels = channels
        self._log(
            "RC_OVERRIDE_OBSERVED_AFTER_MQTT",
            sequence=self.last_publish_sequence,
            mqtt_to_rc_observation_s=age_s,
            channels=channels,
        )

    def _connection_changed(self, connected: bool) -> None:
        self.mqtt_connected = bool(connected)

    def _mqtt_message_received(
        self,
        raw_payload: bytes,
        retained: bool,
        qos: int,
    ) -> None:
        self.pending_messages.put(
            classify_mqtt_message(
                raw_payload,
                retained=retained,
                qos=qos,
                own_registry=self.own_messages,
            )
        )

    def _publish_actions(self, actions: list[PublishAction]) -> None:
        if not actions:
            return
        if self.transport is None or not self.mqtt_connected:
            self.abort_reason = self.abort_reason or "MQTT_DISCONNECTED"
            return
        for action in actions:
            try:
                with self.transport_lock:
                    tracked = publish_action_tracked(
                        self.transport,
                        self.own_messages,
                        action,
                        self.topic,
                    )
                mid = tracked.mid
                self._log(
                    "MQTT_PUBLISH", kind=action.kind, sequence=action.payload["sequence"],
                    payload_hash=tracked.payload_hash, qos=action.qos, retain=False, mid=mid,
                    payload_timestamp=action.payload["timestamp"],
                    throttle=action.payload.get("throttle"),
                    steering=action.payload.get("steering"),
                    release=bool(action.payload.get("release", False)),
                )
                sent_event = (
                    "MOTION_COMMAND_SENT"
                    if action.kind == "MOTION"
                    else f"{action.kind}_SENT"
                )
                self._log(
                    sent_event,
                    sequence=action.payload["sequence"],
                    payload_timestamp=action.payload["timestamp"],
                    throttle=action.payload.get("throttle"),
                    steering=action.payload.get("steering"),
                    release=bool(action.payload.get("release", False)),
                    mid=mid,
                )
                self.motion_command_sent = action.kind == "MOTION"
                self.last_publish_monotonic = time.monotonic()
                self.last_publish_sequence = int(action.payload["sequence"])
                self.pub_neutral.publish(Bool(data=action.kind == "NEUTRAL"))
                self.pub_release.publish(Bool(data=action.kind == "RELEASE"))
            except Exception as exc:
                self.abort_reason = f"MQTT_PUBLISH_FAILED:{type(exc).__name__}"
                self.core.aborted = True
                self.core.abort_reason = self.abort_reason
                self.core.held = False
                self.core.control_acquired = False
                self.motion_command_sent = False
                self.get_logger().error(self.abort_reason)
                break

    def _process_incoming(self) -> None:
        while True:
            try:
                message = self.pending_messages.get_nowait()
            except queue.Empty:
                break
            fields = {
                "classification": message.classification,
                "retained": message.retained,
                "source": message.source,
                "session_id": message.session_id,
                "sequence": message.sequence,
                "payload_hash": message.payload_hash,
                "throttle": message.throttle,
                "steering": message.steering,
                "release": message.release,
                "qos": message.qos,
                "matched_pending_own": message.matched_pending_own,
                "matched_completed_own": message.matched_completed_own,
                "pending_age_s": message.pending_age_s,
            }
            self._log("MQTT_MESSAGE_CLASSIFIED", **fields)
            if message.classification == OWN_MQTT_ECHO:
                if (
                    message.release
                    or
                    abs(float(message.throttle or 0.0)) > 1e-9
                    or abs(float(message.steering or 0.0)) > 1e-9
                ):
                    self.own_echo_received = True
                if message.release:
                    self.release_echo_received = True
                self._log(
                    "OWN_MQTT_ECHO",
                    **fields,
                )
                continue
            if (
                not message.retained
                and message.classification in (BENIGN_RELEASE, BENIGN_NEUTRAL)
            ):
                continue
            actions = self.core.handle_classified(message)
            self.foreign_detected = True
            self.abort_reason = self.core.abort_reason
            if message.classification == ACTIVE_FOREIGN_COMMAND:
                event = "FOREIGN_ACTIVE_COMMAND"
            elif message.classification == UNKNOWN_SCHEMA:
                event = "FOREIGN_UNKNOWN_SCHEMA"
            else:
                event = "FOREIGN_RETAINED_MESSAGE"
            self._log(event, abort_reason=self.abort_reason, **fields)
            if actions:
                self._publish_actions(actions)

    def _tick(self) -> None:
        now = time.monotonic()
        self.motion_command_sent = False
        self.mqtt_ack_received = False
        self.own_echo_received = False
        self.release_echo_received = False
        self._process_incoming()
        while True:
            try:
                mid = self.acknowledged_mids.get_nowait()
            except queue.Empty:
                break
            match = self.own_messages.acknowledge(mid)
            if match.kind == "MOTION":
                self.mqtt_ack_received = True
            self._log(
                "MQTT_LOCAL_ACK",
                mid=mid,
                matched_pending_own=match.matched_pending_own,
                matched_completed_own=match.matched_completed_own,
                pending_age_s=match.pending_age_s,
            )

        guardian_fresh = (
            self.guardian_heartbeat_t > 0.0
            and now - self.guardian_heartbeat_t <= self.limits.heartbeat_timeout_s
        )
        # STOP remains a zero-output safety command. It may publish neutral once
        # the guardian has opened the actuator path without claiming that motion
        # itself is allowed.
        allowed = (
            (
                self.command_publish_allowed
                or self.motion_allowed
                or (
                    self.actuator_path_ready
                    and self.command in ("STOP", "HOLD_COURSE")
                )
            )
            and guardian_fresh
        )
        if self.core.held and not guardian_fresh:
            self._publish_actions(self.core.abort("GUARDIAN_HEARTBEAT_STALE"))
            self.abort_reason = self.core.abort_reason
        elif self.core.held and (now - self.command_t > self.limits.command_timeout_s):
            self._publish_actions(self.core.abort("SAFE_COMMAND_STALE"))
            self.abort_reason = self.core.abort_reason
        elif self.core.held and self.failsafe:
            if self.hold_stop_on_failsafe:
                self.command = "STOP"
                self.left = self.right = 0.0
                self._publish_actions(
                    self.core.hold_failsafe_stop(now=time.time())
                )
            else:
                self._publish_actions(
                    self.core.abort("FAILSAFE_ACTIVE")
                )
                self.abort_reason = self.core.abort_reason
        elif not self.core.aborted:
            actions = self.core.update(self.command, self.left, self.right, allowed, now=time.time())
            self._publish_actions(actions)
            if self.core.aborted:
                self.abort_reason = self.core.abort_reason

        mapped = canonical_thruster_mapping(
            self.command,
            self.limits,
            source_left=self.left,
            source_right=self.right,
        )
        throttle = mapped.throttle_percent
        steering = mapped.steering_percent
        mapping_reason = mapped.reason
        raw_throttle = 100.0 * (self.left + self.right) / 2.0
        raw_steering = 100.0 * (self.left - self.right) / 2.0
        if mapping_reason != "VALID":
            throttle = steering = 0.0
        signature = (
            self.command, round(raw_throttle, 4), round(raw_steering, 4),
            round(throttle, 4), round(steering, 4), allowed,
        )
        if signature != self.last_request_signature:
            self._log(
                "COMMAND_REQUEST",
                safe_command=self.command,
                preview_throttle_percent=self.preview_throttle,
                preview_steering_percent=self.preview_steering,
                before_clamp={"throttle": raw_throttle, "steering": raw_steering},
                after_clamp={"throttle": throttle, "steering": steering},
                motion_allowed=allowed,
                mapping_reason=mapping_reason,
                mapped_command=mapped.command,
                requested_steering_pwm=mapped.requested_steering_pwm,
                requested_throttle_pwm=mapped.requested_throttle_pwm,
            )
            self.last_request_signature = signature
        self.pub_session.publish(String(data=self.core.session_id))
        self.pub_command.publish(String(data=self.command))
        self.pub_throttle.publish(Float32(data=float(throttle)))
        self.pub_steering.publish(Float32(data=float(steering)))
        self.pub_heartbeat.publish(Float32(data=float(time.monotonic())))
        self.pub_mqtt_connected.publish(Bool(data=self.mqtt_connected))
        self.pub_mqtt_enabled.publish(Bool(data=bool(self._p("mqtt_publish_enabled"))))
        self.pub_abort.publish(String(data=self.abort_reason))
        self.pub_foreign.publish(Bool(data=self.foreign_detected))
        self.pub_motion_sent.publish(Bool(data=self.motion_command_sent))
        self.pub_mqtt_ack.publish(Bool(data=self.mqtt_ack_received))
        self.pub_own_echo.publish(Bool(data=self.own_echo_received))
        self.pub_release_echo.publish(
            Bool(data=self.release_echo_received)
        )
        self.pub_control_acquired.publish(Bool(data=self.core.control_acquired))
        self.pub_mapped_command.publish(String(data=mapped.command))

    def safe_shutdown(self) -> None:
        if self.transport is not None and self.mqtt_connected and not self.foreign_detected:
            self._publish_actions(self.core.shutdown(now=time.time()))
        self._log("SHUTDOWN", abort_reason=self.abort_reason)
        if self.transport is not None:
            self.transport.stop()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = GuardedThrusterTestAdapter()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.safe_shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
