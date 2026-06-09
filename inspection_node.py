#!/usr/bin/env python3

import time
import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32

from move_robot import move_robot_to_good_bin, move_robot_to_reject_bin

from top_view_pipeline import validate_top_view
from side_view_pipeline import validate_side_view


class InspectionNode(Node):

    SERVO_TOPIC = '/inspection_servo_cmd'
    ROTATE_WAIT_SEC = 2.0

    def __init__(self):
        super().__init__('inspection_node')

        self.servo_pub = self.create_publisher(Float32, self.SERVO_TOPIC, 10)

        self.get_logger().info("Inspection node started")

        # ✅ IMPORTANT (non-bloquant)
        self.create_timer(1.0, self.run_inspection_once)
        self.done = False


    def run_inspection_once(self):
        if self.done:
            return

        self.done = True

        self.run_inspection()


    def run_inspection(self):

        self.rotate_platform(0.0)

        self.get_logger().info("Running top-view inspection")
        top_status, top_details = validate_top_view()
        self.get_logger().info(f"Top => {top_status} | {top_details}")

        self.get_logger().info("Running side-view inspection")
        side_status, side_details = validate_side_view()
        self.get_logger().info(f"Side => {side_status} | {side_details}")

        if top_status == "Defected" or side_status == "Defected":
            self.handle_defective_part(top_details, side_details)
            return

        self.get_logger().info("Rotating for second inspection")
        self.rotate_platform(180.0)

        side2_status, side2_details = validate_side_view()

        if side2_status == "Defected":
            self.handle_defective_part(side2_details)
        else:
            self.handle_good_part()


    def handle_good_part(self):
        self.get_logger().info("✅ GOOD PART")
        move_robot_to_good_bin()


    def handle_defective_part(self, *details):
        self.get_logger().warn(f"❌ DEFECTIVE: {details}")
        move_robot_to_reject_bin()


    def rotate_platform(self, angle):

        msg = Float32()
        msg.data = angle
        self.servo_pub.publish(msg)

        self.get_logger().info(f"Rotate {angle}°")

        start = time.time()
        while time.time() - start < self.ROTATE_WAIT_SEC:
            rclpy.spin_once(self, timeout_sec=0.1)


def main(args=None):
    rclpy.init(args=args)
    node = InspectionNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()