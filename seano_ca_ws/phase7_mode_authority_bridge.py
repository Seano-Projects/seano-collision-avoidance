#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool
from mavros_msgs.msg import State

class Phase7ModeAuthorityBridge(Node):
    def __init__(self):
        super().__init__("phase7_mode_authority_bridge")
        self.pub_auto = self.create_publisher(Bool, "/seano/auto_enable", 10)
        self.pub_manual = self.create_publisher(Bool, "/seano/operator_manual_authority", 10)
        self.last_mode = "UNKNOWN"
        self.last_connected = False
        self.create_subscription(State, "/mavros/state", self.on_state, 10)
        self.create_timer(0.2, self.tick)
        self.get_logger().info("Bridge ready: /mavros/state -> /seano/auto_enable + /seano/operator_manual_authority")

    def on_state(self, msg):
        self.last_mode = msg.mode or "UNKNOWN"
        self.last_connected = bool(msg.connected)

    def tick(self):
        is_auto = self.last_connected and self.last_mode.upper() == "AUTO"

        auto_msg = Bool()
        auto_msg.data = is_auto
        self.pub_auto.publish(auto_msg)

        manual_msg = Bool()
        manual_msg.data = not is_auto
        self.pub_manual.publish(manual_msg)

        self.get_logger().info(
            f"mavros_mode={self.last_mode} connected={self.last_connected} "
            f"auto_enable={auto_msg.data} operator_manual_authority={manual_msg.data}",
            throttle_duration_sec=1.0
        )

def main():
    rclpy.init()
    node = Phase7ModeAuthorityBridge()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
