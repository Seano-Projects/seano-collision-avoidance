#!/usr/bin/env python3
"""Hardware-test HUD overlay; never infers external application from ROS intent."""

from __future__ import annotations

import time

from cv_bridge import CvBridge
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Bool, Float32, String

from .thruster_test_hud import render_hardware_header


class ThrusterTestHud(Node):
    def __init__(self) -> None:
        super().__init__("thruster_test_hud_node")
        self.bridge = CvBridge()
        self.values = {
            "desired": "STALE", "safe": "STALE", "preview": "STALE",
            "command": "NONE", "status": "PREVIEW_ONLY", "session": "",
            "motion": False, "mqtt_connected": False, "mqtt_enabled": False,
            "foreign": False, "abort": "", "neutral": False, "release": False,
            "blocked": "", "fcu_connected": False, "fcu_armed": False,
            "ca_fresh": False, "adapter_fresh": False, "foreign_clean": False,
            "web_video": False,
            "fcu_mode": "UNKNOWN", "required_mode": "MANUAL",
            "rc_publisher": "UNAVAILABLE", "software_ready": False,
            "mode_ready": False, "armed_ready": False,
            "physical_ready": False, "motion_sent": False,
            "throttle": 0.0, "steering": 0.0,
        }
        self.create_subscription(Image, "/ca/debug_image", self._image, 1)
        self._sub(String, "/ca/command", "desired")
        self._sub(String, "/ca/command_safe", "safe")
        self._sub(String, "/ca/thruster_preview/applied_command", "preview")
        self._sub(String, "/ca/hardware_test/command", "command")
        self._sub(String, "/ca/hardware_test/status", "status")
        self._sub(String, "/ca/hardware_test/session_id", "session")
        self._sub(String, "/ca/hardware_test/abort_reason", "abort")
        self._sub(String, "/ca/hardware_test/blocked_reason", "blocked")
        self._sub(Bool, "/ca/hardware_test/motion_allowed", "motion")
        self._sub(Bool, "/ca/hardware_test/mqtt_connected", "mqtt_connected")
        self._sub(Bool, "/ca/hardware_test/mqtt_publish_enabled", "mqtt_enabled")
        self._sub(Bool, "/ca/hardware_test/foreign_command_detected", "foreign")
        self._sub(Bool, "/ca/hardware_test/neutral_sent", "neutral")
        self._sub(Bool, "/ca/hardware_test/release_sent", "release")
        self._sub(Bool, "/ca/hardware_test/fcu_connected", "fcu_connected")
        self._sub(Bool, "/ca/hardware_test/fcu_armed", "fcu_armed")
        self._sub(Bool, "/ca/hardware_test/ca_data_fresh", "ca_fresh")
        self._sub(Bool, "/ca/hardware_test/adapter_heartbeat_fresh", "adapter_fresh")
        self._sub(Bool, "/ca/hardware_test/foreign_window_clean", "foreign_clean")
        self._sub(Bool, "/ca/hardware_test/web_video_available", "web_video")
        self._sub(String, "/ca/hardware_test/fcu_mode", "fcu_mode")
        self._sub(String, "/ca/hardware_test/required_fcu_mode", "required_mode")
        self._sub(String, "/ca/hardware_test/rc_publisher", "rc_publisher")
        self._sub(Bool, "/ca/hardware_test/software_path_ready", "software_ready")
        self._sub(Bool, "/ca/hardware_test/fcu_mode_ready", "mode_ready")
        self._sub(Bool, "/ca/hardware_test/fcu_armed_ready", "armed_ready")
        self._sub(Bool, "/ca/hardware_test/physical_motion_ready", "physical_ready")
        self._sub(Bool, "/ca/hardware_test/motion_command_sent", "motion_sent")
        self._sub(Float32, "/ca/hardware_test/throttle", "throttle")
        self._sub(Float32, "/ca/hardware_test/steering", "steering")
        self.publisher = self.create_publisher(Image, "/ca/hardware_test/debug_image", 1)
        self.heartbeat_publisher = self.create_publisher(
            Float32, "/ca/hardware_test/hud_heartbeat", 10
        )
        self.create_timer(
            0.1,
            lambda: self.heartbeat_publisher.publish(
                Float32(data=float(time.monotonic()))
            ),
        )

    def _sub(self, msg_type, topic: str, key: str) -> None:
        self.create_subscription(msg_type, topic, lambda msg, k=key: self._value(k, msg.data), 10)

    def _value(self, key, value) -> None:
        self.values[key] = value

    def _image(self, msg: Image) -> None:
        try:
            image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception:
            return
        hardware_image = render_hardware_header(image, self.values)
        out = self.bridge.cv2_to_imgmsg(hardware_image, encoding="bgr8")
        out.header = msg.header
        self.publisher.publish(out)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ThrusterTestHud()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
