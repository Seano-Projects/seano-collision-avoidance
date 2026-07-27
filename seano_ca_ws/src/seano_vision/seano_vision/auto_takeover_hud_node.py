#!/usr/bin/env python3
"""Publishes `/ca/debug_image` unchanged below an AUTO takeover header."""

import json
import time

from cv_bridge import CvBridge
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Float32, String

from .auto_takeover_hud import render_auto_takeover_header


class AutoTakeoverHud(Node):
    def __init__(self) -> None:
        super().__init__("auto_takeover_hud_node")
        self.bridge = CvBridge()
        self.status = {"state": "STARTING"}
        self.create_subscription(Image, "/ca/debug_image", self._image, 1)
        self.create_subscription(
            String, "/ca/auto_takeover/status_json", self._status, 10
        )
        self.publisher = self.create_publisher(
            Image, "/ca/auto_takeover/debug_image", 1
        )
        self.heartbeat = self.create_publisher(
            Float32, "/ca/auto_takeover/hud_heartbeat", 10
        )
        self.create_timer(
            0.1,
            lambda: self.heartbeat.publish(Float32(data=float(time.monotonic()))),
        )

    def _status(self, msg: String) -> None:
        try:
            value = json.loads(msg.data)
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        if isinstance(value, dict):
            self.status = value

    def _image(self, msg: Image) -> None:
        try:
            baseline = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception:
            return
        output = render_auto_takeover_header(baseline, self.status)
        result = self.bridge.cv2_to_imgmsg(output, encoding="bgr8")
        result.header = msg.header
        self.publisher.publish(result)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = AutoTakeoverHud()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
