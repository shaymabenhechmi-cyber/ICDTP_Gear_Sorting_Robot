#!/usr/bin/env python3

import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32

from move_robot import move_robot_to_good_bin, move_robot_to_reject_bin

# Import your pipelines
from top_view_pipeline import validate_top_view
from side_view_pipeline import validate_side_view


class InspectionNode(Node):

    SERVO_TOPIC      = '/inspection_servo_cmd'
    SERVO_STATE_TOPIC = '/inspection_servo_state'

    # How long to wait (s) for the platform to finish rotating
    ROTATE_WAIT_SEC  = 2.0

    def __init__(self):
        super().__init__('inspection_node')

        # Publisher → platform_state_node
        self.servo_pub = self.create_publisher(Float32, self.SERVO_TOPIC, 10)

        self.get_logger().info("Inspection node started")
        self.run_inspection()

    # ─────────────────────────────────────────────────────────────
    # Main inspection sequence
    # ─────────────────────────────────────────────────────────────
    def run_inspection(self):
        self.rotate_platform(0.0)
        # ── First inspection ──────────────────────────────────────
        self.get_logger().info("Running top-view inspection")
        top_status, top_details = validate_top_view()
        self.get_logger().info(f"Top View  => {top_status} | {top_details}")

        self.get_logger().info("Running side-view inspection")
        side_status, side_details = validate_side_view()
        self.get_logger().info(f"Side View => {side_status} | {side_details}")

        if top_status == "Defected" or side_status == "Defected":
            self.handle_defective_part(top_details, side_details)
            return

        self.get_logger().info("Part passed first inspection — rotating platform")

        # ── Rotate platform for second side inspection ─────────────
        self.rotate_platform(180.0)

        # ── Second side inspection ────────────────────────────────
        self.get_logger().info("Running second side-view inspection")
        side2_status, side2_details = validate_side_view()
        self.get_logger().info(f"Second Side => {side2_status} | {side2_details}")

        # ── Final decision ────────────────────────────────────────
        if side2_status == "Defected":
            self.handle_defective_part(side2_details)
        else:
            self.handle_good_part()

    # ─────────────────────────────────────────────────────────────
    # Outcome handlers
    # ─────────────────────────────────────────────────────────────
    def handle_good_part(self):
        self.get_logger().info("GOOD PART — moving to good bin")
        move_robot_to_good_bin()

    def handle_defective_part(self, *details):
        self.get_logger().warn(f"DEFECTIVE PART: {details}")
        move_robot_to_reject_bin()

    # ─────────────────────────────────────────────────────────────
    # Platform rotation
    # ─────────────────────────────────────────────────────────────
    def rotate_platform(self, angle: float):
        """
        Send an angle command to platform_state_node and block until
        the servo has had time to reach the target position.
        """
        self.get_logger().info(f"Sending servo command: {angle}°")

        msg = Float32()
        msg.data = angle
        self.servo_pub.publish(msg)

        # Give the servo time to physically reach the target
        self.get_logger().info(
            f"Waiting {self.ROTATE_WAIT_SEC}s for platform rotation..."
        )
        start = time.time()
        while time.time() - start < self.ROTATE_WAIT_SEC:
            rclpy.spin_once(self, timeout_sec=0.1)

        self.get_logger().info("Platform rotation complete")


# ── Entry point ────────────────────────────────────────────────
def main(args=None):
    rclpy.init(args=args)
    node = InspectionNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()