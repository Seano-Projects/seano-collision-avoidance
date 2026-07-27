#!/usr/bin/env python3
"""Local-only thruster conversion preview. This node has no hardware transport."""

from __future__ import annotations

import json
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, Float32, Int32, String

from .risk_policy import normalize_command_details
from .thruster_preview import evaluate_actuator_path_ready, normalized_to_preview


class ThrusterAdapterPreview(Node):
    def __init__(self) -> None:
        super().__init__("thruster_adapter_preview_node")
        for name, value in (
            ("enabled", True), ("dry_run", True), ("command_timeout_s", 1.0),
            ("input_timeout_s", 1.0), ("maximum_throttle_percent", 100.0),
            ("maximum_steering_percent", 100.0),
            ("external_interface_confirmed", False),
            ("external_arbitration_confirmed", False),
            ("hardware_output_enabled", False),
            ("publish_actuator_path_ready", True), ("rate_hz", 10.0),
        ):
            self.declare_parameter(name, value)

        self.left = self.right = 0.0
        self.left_t = self.right_t = self.command_t = 0.0
        self.command = "HOLD_COURSE"
        self.failsafe = False
        self.auto_enable = self.rc_override_enable = False

        self.create_subscription(Float32, "/seano/left_cmd", self._left, 10)
        self.create_subscription(Float32, "/seano/right_cmd", self._right, 10)
        self.create_subscription(Bool, "/seano/auto_enable", self._auto, 10)
        self.create_subscription(Bool, "/seano/rc_override_enable", self._override, 10)
        self.create_subscription(String, "/ca/command_safe", self._command, 10)
        self.create_subscription(Bool, "/ca/failsafe_active", self._failsafe, 10)

        self.pub_payload = self.create_publisher(String, "/ca/thruster_preview/payload", 10)
        self.pub_throttle = self.create_publisher(Float32, "/ca/thruster_preview/throttle", 10)
        self.pub_steering = self.create_publisher(Float32, "/ca/thruster_preview/steering", 10)
        self.pub_pwm1 = self.create_publisher(Int32, "/ca/thruster_preview/pwm_steering", 10)
        self.pub_pwm3 = self.create_publisher(Int32, "/ca/thruster_preview/pwm_throttle", 10)
        self.pub_command = self.create_publisher(String, "/ca/thruster_preview/applied_command", 10)
        self.pub_ready = self.create_publisher(Bool, "/ca/thruster_preview/ready", 10)
        self.pub_reason = self.create_publisher(String, "/ca/thruster_preview/blocked_reason", 10)
        self.pub_path_ready = self.create_publisher(Bool, "/ca/actuator_path_ready", 10)
        self.pub_dry_run = self.create_publisher(Bool, "/ca/thruster_preview/dry_run", 10)
        self.pub_hardware = self.create_publisher(Bool, "/ca/thruster_preview/hardware_output_enabled", 10)
        hz = max(1.0, float(self.get_parameter("rate_hz").value))
        self.create_timer(1.0 / hz, self._tick)
        self.get_logger().warn("Thruster adapter PREVIEW only: no external transport or hardware output.")

    def _left(self, msg): self.left, self.left_t = float(msg.data), time.monotonic()
    def _right(self, msg): self.right, self.right_t = float(msg.data), time.monotonic()
    def _auto(self, msg): self.auto_enable = bool(msg.data)
    def _override(self, msg): self.rc_override_enable = bool(msg.data)
    def _command(self, msg): self.command, _, _ = normalize_command_details(msg.data); self.command_t = time.monotonic()
    def _failsafe(self, msg): self.failsafe = bool(msg.data)

    def _tick(self) -> None:
        now = time.monotonic()
        input_timeout = max(0.01, float(self.get_parameter("input_timeout_s").value))
        command_timeout = max(0.01, float(self.get_parameter("command_timeout_s").value))
        ready, reason = evaluate_actuator_path_ready(
            enabled=bool(self.get_parameter("enabled").value),
            left_fresh=(now - self.left_t) <= input_timeout,
            right_fresh=(now - self.right_t) <= input_timeout,
            command_fresh=(now - self.command_t) <= command_timeout,
            failsafe_active=self.failsafe,
            dry_run=bool(self.get_parameter("dry_run").value),
            external_interface_confirmed=bool(self.get_parameter("external_interface_confirmed").value),
            external_arbitration_confirmed=bool(self.get_parameter("external_arbitration_confirmed").value),
            hardware_output_enabled=bool(self.get_parameter("hardware_output_enabled").value),
        )
        preview = normalized_to_preview(
            self.left, self.right,
            float(self.get_parameter("maximum_throttle_percent").value),
            float(self.get_parameter("maximum_steering_percent").value),
        )
        payload = json.dumps({"throttle": round(preview["throttle"], 3), "steering": round(preview["steering"], 3)}, separators=(",", ":"))
        self.pub_payload.publish(String(data=payload))
        self.pub_throttle.publish(Float32(data=float(preview["throttle"])))
        self.pub_steering.publish(Float32(data=float(preview["steering"])))
        self.pub_pwm1.publish(Int32(data=preview["pwm_ch1"]))
        self.pub_pwm3.publish(Int32(data=preview["pwm_ch3"]))
        self.pub_command.publish(String(data=self.command))
        self.pub_ready.publish(Bool(data=ready))
        if bool(self.get_parameter("publish_actuator_path_ready").value):
            self.pub_path_ready.publish(Bool(data=ready))
        self.pub_reason.publish(String(data=reason))
        self.pub_dry_run.publish(Bool(data=bool(self.get_parameter("dry_run").value)))
        self.pub_hardware.publish(Bool(data=bool(self.get_parameter("hardware_output_enabled").value)))


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ThrusterAdapterPreview()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
