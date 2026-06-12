#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
import lgpio
import time

from std_msgs.msg import Float32


class PlatformStateNode(Node):

    SERVO_PIN = 18  # GPIO18

    def __init__(self):
        super().__init__('platform_state_node')

        # ─────────────────────────────
        # ROS interfaces
        # ─────────────────────────────
        self.cmd_sub = self.create_subscription(
            Float32,
            '/inspection_servo_cmd',
            self.cmd_callback,
            10
        )

        self.state_pub = self.create_publisher(
            Float32,
            '/inspection_servo_state',
            10
        )

        # ─────────────────────────────
        # GPIO (Pi 5 FIX)
        # ─────────────────────────────
        self.h = lgpio.gpiochip_open(4)
        lgpio.gpio_claim_output(self.h, self.SERVO_PIN)

        self.current_angle = 0.0

        self.get_logger().info("Platform State Node started (lgpio Pi5 ready)")

    # ─────────────────────────────
    # ROS callback
    # ─────────────────────────────
    def cmd_callback(self, msg: Float32):

        target = float(msg.data)
        self.get_logger().info(f"Servo target: {target}°")

        self.set_angle(target)

        self.current_angle = target
        self.publish_state()

    # ─────────────────────────────
    # Hardware control (LGPIO)
    # ─────────────────────────────
    def set_angle(self, angle):
        angle = max(0, min(180, angle))
        pulse = int(500 + (angle / 180.0) * 2000)  # cast to int
        lgpio.tx_servo(self.h, self.SERVO_PIN, pulse)
        time.sleep(0.2)
    # ─────────────────────────────
    # Publish state
    # ─────────────────────────────
    def publish_state(self):

        msg = Float32()
        msg.data = float(self.current_angle)
        self.state_pub.publish(msg)

    # ─────────────────────────────
    # Cleanup
    # ─────────────────────────────
    def destroy_node(self):

        lgpio.gpiochip_close(self.h)
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PlatformStateNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()