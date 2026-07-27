#!/usr/bin/env python3
"""Independent fail-closed guardian for the shared-MQTT thruster test."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import rclpy
from mavros_msgs.msg import State
from rclpy.node import Node
from std_msgs.msg import Bool, Float32, String

from .risk_policy import normalize_command_details
from .thruster_test_mqtt import PahoSharedTopicTransport
from .thruster_test_safety import (
    AdapterCore, GuardianCore, GuardianInputs, SHARED_TOPIC, StaticGates, TestLimits,
)


class ThrusterTestSafetyGuardian(Node):
    def __init__(self) -> None:
        super().__init__("thruster_test_safety_guardian_node")
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
            ("maximum_throttle_percent", 10.0),
            ("maximum_steering_percent", 15.0),
            ("command_timeout_s", 0.30),
            ("heartbeat_timeout_s", 0.50),
            ("maximum_motion_duration_s", 2.0),
            ("mqtt_qos", 1),
            ("mqtt_retain", False),
            ("foreign_observation_window_s", 1.0),
            ("startup_grace_period_s", 8.0),
            ("web_video_available", False),
            ("required_fcu_mode", "MANUAL"),
            ("session_id", ""),
            ("log_dir", ""),
            ("rate_hz", 20.0),
        )
        for name, value in defaults:
            self.declare_parameter(name, value)

        self.gates = StaticGates(
            hardware_test_enabled=bool(self._p("hardware_test_enabled")),
            mqtt_publish_enabled=bool(self._p("mqtt_publish_enabled")),
            operator_confirmed=bool(self._p("operator_confirmed")),
            shared_mqtt_test_confirmed=bool(self._p("shared_mqtt_test_confirmed")),
            tether_confirmed=bool(self._p("tether_confirmed")),
            emergency_stop_confirmed=bool(self._p("emergency_stop_confirmed")),
            exclusive_test_window_confirmed=bool(self._p("exclusive_test_window_confirmed")),
            foreign_command_monitor_enabled=bool(self._p("foreign_command_monitor_enabled")),
        )
        self.limits = TestLimits(
            maximum_throttle_percent=float(self._p("maximum_throttle_percent")),
            maximum_steering_percent=float(self._p("maximum_steering_percent")),
            command_timeout_s=float(self._p("command_timeout_s")),
            heartbeat_timeout_s=float(self._p("heartbeat_timeout_s")),
            maximum_motion_duration_s=float(self._p("maximum_motion_duration_s")),
            reverse_allowed=bool(self._p("reverse_allowed")),
            mqtt_qos=int(self._p("mqtt_qos")),
            mqtt_retain=bool(self._p("mqtt_retain")),
        )
        self.core = GuardianCore(
            self.gates,
            self.limits,
            observation_window_s=float(self._p("foreign_observation_window_s")),
            startup_grace_s=float(self._p("startup_grace_period_s")),
        )
        self.started_at = 0.0
        self.adapter_heartbeat_at = self.command_at = self.safe_command_at = 0.0
        self.hud_heartbeat_at = 0.0
        self.command = "STALE"
        self.failsafe = True
        self.lost_perception = True
        self.mqtt_connected = False
        self.foreign_command = False
        self.foreign_command_reason = ""
        self.operator_enable = bool(self._p("operator_confirmed"))
        self.throttle = self.steering = 0.0
        self.fcu_connected = self.fcu_armed = False
        self.fcu_mode = ""
        self.last_status = "PREVIEW_ONLY"
        self.last_abort = ""
        self.last_blocked = ""
        self.neutral_sent = self.release_sent = False
        self.abort_publish_ticks = 0
        self.emergency_abort_sent = False
        self.backup_connected = False
        self.backup_transport = None
        self.emergency_core = AdapterCore(limits=self.limits, session_id=str(self._p("session_id")))
        self.log_path = self._prepare_log_path(str(self._p("log_dir")))

        self.create_subscription(Float32, "/ca/hardware_test/heartbeat", self._adapter_heartbeat, 10)
        self.create_subscription(Float32, "/ca/hardware_test/hud_heartbeat", self._hud_heartbeat, 10)
        self.create_subscription(String, "/ca/thruster_preview/applied_command", self._command, 10)
        self.create_subscription(String, "/ca/command_safe", self._safe_command, 10)
        self.create_subscription(Bool, "/ca/failsafe_active", self._failsafe, 10)
        self.create_subscription(String, "/ca/mode", self._ca_mode, 10)
        self.create_subscription(Bool, "/ca/hardware_test/mqtt_connected", self._mqtt, 10)
        self.create_subscription(Bool, "/ca/hardware_test/foreign_command_detected", self._foreign, 10)
        self.create_subscription(
            String,
            "/ca/hardware_test/adapter_abort_reason",
            self._foreign_reason,
            10,
        )
        self.create_subscription(Float32, "/ca/hardware_test/throttle", self._throttle, 10)
        self.create_subscription(Float32, "/ca/hardware_test/steering", self._steering, 10)
        self.create_subscription(Bool, "/ca/hardware_test/operator_enable", self._operator, 10)
        self.create_subscription(Bool, "/ca/hardware_test/neutral_sent", self._neutral, 10)
        self.create_subscription(Bool, "/ca/hardware_test/release_sent", self._release, 10)
        self.create_subscription(State, "/mavros/state", self._fcu, 10)

        self.pub_status = self.create_publisher(String, "/ca/hardware_test/status", 10)
        self.pub_session = self.create_publisher(String, "/ca/hardware_test/session_id", 10)
        self.pub_motion = self.create_publisher(Bool, "/ca/hardware_test/motion_allowed", 10)
        self.pub_abort = self.create_publisher(String, "/ca/hardware_test/abort_reason", 10)
        self.pub_blocked = self.create_publisher(String, "/ca/hardware_test/blocked_reason", 10)
        self.pub_fcu_connected = self.create_publisher(Bool, "/ca/hardware_test/fcu_connected", 10)
        self.pub_fcu_armed = self.create_publisher(Bool, "/ca/hardware_test/fcu_armed", 10)
        self.pub_ca_fresh = self.create_publisher(Bool, "/ca/hardware_test/ca_data_fresh", 10)
        self.pub_adapter_fresh = self.create_publisher(Bool, "/ca/hardware_test/adapter_heartbeat_fresh", 10)
        self.pub_foreign_clean = self.create_publisher(Bool, "/ca/hardware_test/foreign_window_clean", 10)
        self.pub_web_video = self.create_publisher(Bool, "/ca/hardware_test/web_video_available", 10)
        self.pub_software_ready = self.create_publisher(Bool, "/ca/hardware_test/software_path_ready", 10)
        self.pub_mode_ready = self.create_publisher(Bool, "/ca/hardware_test/fcu_mode_ready", 10)
        self.pub_armed_ready = self.create_publisher(Bool, "/ca/hardware_test/fcu_armed_ready", 10)
        self.pub_physical_ready = self.create_publisher(Bool, "/ca/hardware_test/physical_motion_ready", 10)
        self.pub_fcu_mode = self.create_publisher(String, "/ca/hardware_test/fcu_mode", 10)
        self.pub_required_mode = self.create_publisher(String, "/ca/hardware_test/required_fcu_mode", 10)
        self.pub_rc_publisher = self.create_publisher(String, "/ca/hardware_test/rc_publisher", 10)
        self.pub_path_ready = self.create_publisher(Bool, "/ca/actuator_path_ready", 10)
        self.pub_guardian_heartbeat = self.create_publisher(Float32, "/ca/hardware_test/guardian_heartbeat", 10)
        valid_limits, _ = self.limits.validate_first_test()
        if valid_limits and not self.gates.closed_reasons():
            try:
                self.backup_transport = PahoSharedTopicTransport(
                    client_id=f"ca-guardian-{str(self._p('session_id'))[:12]}",
                    topic=SHARED_TOPIC,
                    qos=self.limits.mqtt_qos,
                    on_message=lambda payload, retained, qos: None,
                    on_connection=self._backup_connection,
                    on_ack=lambda mid: self._log("GUARDIAN_MQTT_LOCAL_ACK", mid=int(mid)),
                )
                self.backup_transport.start()
            except Exception as exc:
                self._log("GUARDIAN_MQTT_INIT_FAILED", error_type=type(exc).__name__)
        # Start the grace clock after potentially blocking transport setup. This
        # guarantees that the first ROS callbacks receive the full grace period.
        self.started_at = time.monotonic()
        hz = max(2.0, float(self._p("rate_hz")))
        self.create_timer(1.0 / hz, self._tick)
        self.get_logger().warn("Independent hardware-test guardian active; motion defaults blocked.")

    def _p(self, name):
        return self.get_parameter(name).value

    def _prepare_log_path(self, log_dir: str) -> Path | None:
        if not log_dir:
            return None
        path = Path(log_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path / "guardian_events.jsonl"

    def _log(self, event: str, **data) -> None:
        if self.log_path is None:
            return
        record = {
            "timestamp": time.time(),
            "event": event,
            "session_id": str(self._p("session_id")),
            **data,
        }
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")

    def _adapter_heartbeat(self, msg): self.adapter_heartbeat_at = time.monotonic()
    def _hud_heartbeat(self, msg): self.hud_heartbeat_at = time.monotonic()
    def _command(self, msg): self.command, _, _ = normalize_command_details(msg.data); self.command_at = time.monotonic()
    def _safe_command(self, msg): self.command, _, _ = normalize_command_details(msg.data); self.safe_command_at = time.monotonic()
    def _failsafe(self, msg): self.failsafe = bool(msg.data)
    def _ca_mode(self, msg): self.lost_perception = str(msg.data).strip().upper() == "LOST_PERCEPTION"
    def _mqtt(self, msg): self.mqtt_connected = bool(msg.data)
    def _foreign(self, msg): self.foreign_command = bool(msg.data)
    def _foreign_reason(self, msg): self.foreign_command_reason = str(msg.data)
    def _throttle(self, msg): self.throttle = float(msg.data)
    def _steering(self, msg): self.steering = float(msg.data)
    def _operator(self, msg): self.operator_enable = bool(msg.data)
    def _neutral(self, msg): self.neutral_sent = bool(msg.data)
    def _release(self, msg): self.release_sent = bool(msg.data)

    def _fcu(self, msg: State) -> None:
        self.fcu_connected = bool(msg.connected)
        self.fcu_armed = bool(msg.armed)
        self.fcu_mode = str(msg.mode)

    def _backup_connection(self, connected: bool) -> None:
        self.backup_connected = bool(connected)

    def _emergency_abort(self, reason: str) -> None:
        if self.emergency_abort_sent or not self.backup_connected or self.backup_transport is None:
            return
        if reason not in ("ADAPTER_HEARTBEAT_STALE", "MQTT_DISCONNECTED"):
            return
        self.emergency_abort_sent = True
        for action in self.emergency_core.abort(reason, foreign=False):
            raw = json.dumps(action.payload, separators=(",", ":"), sort_keys=True)
            payload_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            try:
                info = self.backup_transport.publish(SHARED_TOPIC, raw, action.qos, False)
                self._log(
                    "GUARDIAN_EMERGENCY_PUBLISH",
                    kind=action.kind,
                    sequence=action.payload["sequence"],
                    payload_hash=payload_hash,
                    retain=False,
                    mid=int(getattr(info, "mid", -1)),
                    abort_reason=reason,
                )
            except Exception as exc:
                self._log("GUARDIAN_EMERGENCY_PUBLISH_FAILED", error_type=type(exc).__name__)
                break

    @staticmethod
    def _full_name(info) -> str:
        namespace = str(info.node_namespace or "/")
        name = str(info.node_name).lstrip("/")
        return f"/{name}" if namespace == "/" else f"{namespace.rstrip('/')}/{name}"

    def _rc_graph(self) -> tuple[int, str, bool]:
        publishers = self.get_publishers_info_by_topic("/mavros/rc/override")
        subscribers = self.get_subscriptions_info_by_topic("/mavros/rc/override")
        publisher_name = self._full_name(publishers[0]) if len(publishers) == 1 else ""
        mavros_rc = any(self._full_name(info) == "/mavros/rc" for info in subscribers)
        return len(publishers), publisher_name, mavros_rc

    def _tick(self) -> None:
        now = time.monotonic()
        publisher_count, publisher_name, subscriber_present = self._rc_graph()
        hud_fresh = (
            self.hud_heartbeat_at > 0.0
            and now - self.hud_heartbeat_at <= self.limits.heartbeat_timeout_s
        )
        decision = self.core.evaluate(GuardianInputs(
            now=now,
            started_at=self.started_at,
            adapter_heartbeat_at=self.adapter_heartbeat_at,
            command_at=self.command_at,
            safe_command_at=self.safe_command_at,
            command=self.command,
            failsafe=self.failsafe,
            lost_perception=self.lost_perception,
            mqtt_connected=self.mqtt_connected,
            foreign_command=self.foreign_command,
            foreign_command_reason=self.foreign_command_reason,
            operator_enable=self.operator_enable,
            throttle_percent=self.throttle,
            steering_percent=self.steering,
            fcu_connected=self.fcu_connected,
            fcu_armed=self.fcu_armed,
            fcu_mode=self.fcu_mode,
            required_fcu_mode=str(self._p("required_fcu_mode")),
            rc_publisher_count=publisher_count,
            rc_publisher_name=publisher_name,
            rc_subscriber_present=subscriber_present,
            web_video_available=bool(self._p("web_video_available")),
            hud_heartbeat_fresh=hud_fresh,
            guardian_heartbeat_fresh=True,
        ))
        visible_status = decision.status
        self.pub_status.publish(String(data=visible_status))
        self.pub_session.publish(String(data=str(self._p("session_id"))))
        self.pub_motion.publish(Bool(data=decision.motion_allowed))
        self.pub_abort.publish(String(data=decision.abort_reason))
        self.pub_blocked.publish(String(data=decision.blocked_reason))
        self.pub_path_ready.publish(Bool(data=decision.actuator_path_ready))
        self.pub_guardian_heartbeat.publish(Float32(data=float(now)))
        adapter_fresh = (
            self.adapter_heartbeat_at > 0.0
            and now - self.adapter_heartbeat_at <= self.limits.heartbeat_timeout_s
        )
        ca_fresh = (
            self.command_at > 0.0
            and self.safe_command_at > 0.0
            and now - self.command_at <= self.limits.command_timeout_s
            and now - self.safe_command_at <= self.limits.command_timeout_s
            and not self.failsafe
            and not self.lost_perception
        )
        required_mode = str(self._p("required_fcu_mode")).strip().upper()
        mode_ready = bool(required_mode) and self.fcu_mode.strip().upper() == required_mode
        software_ready = (
            self.fcu_connected
            and ca_fresh
            and adapter_fresh
            and self.mqtt_connected
            and not self.foreign_command
            and bool(self._p("web_video_available"))
            and hud_fresh
            and publisher_count == 1
            and publisher_name == "/usv/thruster"
            and subscriber_present
        )
        physical_ready = (
            software_ready
            and mode_ready
            and self.fcu_armed
            and decision.actuator_path_ready
        )
        self.pub_fcu_connected.publish(Bool(data=self.fcu_connected))
        self.pub_fcu_armed.publish(Bool(data=self.fcu_armed))
        self.pub_ca_fresh.publish(Bool(data=ca_fresh))
        self.pub_adapter_fresh.publish(Bool(data=adapter_fresh))
        self.pub_foreign_clean.publish(Bool(data=not self.foreign_command))
        self.pub_web_video.publish(Bool(data=bool(self._p("web_video_available"))))
        self.pub_software_ready.publish(Bool(data=software_ready))
        self.pub_mode_ready.publish(Bool(data=mode_ready))
        self.pub_armed_ready.publish(Bool(data=self.fcu_armed))
        self.pub_physical_ready.publish(Bool(data=physical_ready))
        self.pub_fcu_mode.publish(String(data=self.fcu_mode))
        self.pub_required_mode.publish(String(data=required_mode))
        self.pub_rc_publisher.publish(String(data=publisher_name or "UNAVAILABLE"))
        if (
            visible_status != self.last_status
            or decision.abort_reason != self.last_abort
            or decision.blocked_reason != getattr(self, "last_blocked", "")
        ):
            self._log(
                "GUARDIAN_DECISION",
                status=visible_status,
                motion_allowed=decision.motion_allowed,
                abort_reason=decision.abort_reason,
                blocked_reason=decision.blocked_reason,
                ca_data_fresh=ca_fresh,
                guardian_heartbeat_fresh=True,
                adapter_heartbeat_fresh=adapter_fresh,
                mqtt_connected=self.mqtt_connected,
                foreign_window_clean=not self.foreign_command,
                web_video_available=bool(self._p("web_video_available")),
                hud_heartbeat_fresh=hud_fresh,
                software_path_ready=software_ready,
                fcu_mode_ready=mode_ready,
                fcu_armed_ready=self.fcu_armed,
                physical_motion_ready=physical_ready,
                required_fcu_mode=required_mode,
                fcu_connected=self.fcu_connected,
                fcu_armed=self.fcu_armed,
                fcu_mode=self.fcu_mode,
                rc_publisher_count=publisher_count,
                rc_publisher_name=publisher_name,
                rc_subscriber_present=subscriber_present,
                watchdog={
                    "adapter_age_s": None if self.adapter_heartbeat_at <= 0.0 else now - self.adapter_heartbeat_at,
                    "command_age_s": None if self.command_at <= 0.0 else now - self.command_at,
                    "safe_command_age_s": None if self.safe_command_at <= 0.0 else now - self.safe_command_at,
                },
            )
            self.get_logger().info(
                "status=%s fcu_connected=%s fcu_mode=%s required_mode=%s "
                "mode_ready=%s fcu_armed=%s ca_data_fresh=%s "
                "guardian_heartbeat=true adapter_heartbeat=%s mqtt_connected=%s "
                "foreign_window_clean=%s software_path_ready=%s physical_motion_ready=%s "
                "motion_allowed=%s blocked_reason=%s abort_reason=%s"
                % (
                    visible_status,
                    self.fcu_connected,
                    self.fcu_mode,
                    required_mode,
                    mode_ready,
                    self.fcu_armed,
                    ca_fresh,
                    adapter_fresh,
                    self.mqtt_connected,
                    not self.foreign_command,
                    software_ready,
                    physical_ready,
                    decision.motion_allowed,
                    decision.blocked_reason or "--",
                    decision.abort_reason or "--",
                )
            )
            self.last_status = visible_status
            self.last_abort = decision.abort_reason
            self.last_blocked = decision.blocked_reason
        if decision.abort_reason:
            self._emergency_abort(decision.abort_reason)
            self.abort_publish_ticks += 1
            if self.abort_publish_ticks >= 3:
                self.get_logger().error(
                    f"Guardian latched ABORTED: {decision.abort_reason}; stopping test session."
                )
                rclpy.shutdown()

    def safe_shutdown(self) -> None:
        if self.backup_transport is not None:
            self.backup_transport.stop()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ThrusterTestSafetyGuardian()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.safe_shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
