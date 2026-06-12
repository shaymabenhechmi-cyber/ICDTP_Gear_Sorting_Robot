import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from my_robot_interfaces.msg import RobotCommand
import math


class RobotMiddlewareNode(Node):
    """
    Middleware node for communication between Unity and robot.
    
    Receives target poses on /robot_cmd (my_robot_interfaces/msg/RobotCommand),
    computes inverse kinematics, and publishes joint angles on /joint_states.
    
    The 4-DOF arm:
    - Joint 1: Base rotation (yaw around Z-axis)
    - Joint 2: Shoulder (pitch)
    - Joint 3: Elbow (pitch)
    - Joint 4: Wrist (pitch)
    """

    BASE_HEIGHT = 0.12
    UPPER_ARM_LENGTH = 0.15
    FOREARM_LENGTH = 0.15
    WRIST_LENGTH = 0.06

    JOINT_LIMITS = [
        (-math.pi, math.pi),
        (-math.pi / 2, math.pi / 2),
        (-2.36, 2.36),
        (-math.pi / 2, math.pi / 2),
    ]

    def __init__(self):
        super().__init__('robot_middleware_node')

        self.declare_parameter('publish_rate', 50.0)
        self.declare_parameter('interpolation_speed', 2.0)

        self.publish_rate = self.get_parameter('publish_rate').value
        self.interpolation_speed = self.get_parameter('interpolation_speed').value

        # Publisher for joint angles -> Unity (RobotStateReceiver) reads these
        self.joint_state_pub = self.create_publisher(
            JointState, '/joint_states', 10
        )

        # Subscriber for target poses from Unity (RobotAPIController)
        # Type: my_robot_interfaces/msg/RobotCommand
        # Fields: base_id (string), target_pose (geometry_msgs/Pose), gripper_state (bool)
        self.cmd_sub = self.create_subscription(
            RobotCommand, '/robot_cmd', self.cmd_callback, 10
        )

        self.current_joints = [0.0, 0.0, 0.0, 0.0]
        self.target_joints = [0.0, 0.0, 0.0, 0.0]
        self.joint_names = ['joint_1', 'joint_2', 'joint_3', 'joint_4']
        self.gripper_open = True

        timer_period = 1.0 / self.publish_rate
        self.timer = self.create_timer(timer_period, self.publish_joint_states)

        self.get_logger().info('=== Robot Middleware Node started ===')
        self.get_logger().info('Subscribing: /robot_cmd (my_robot_interfaces/msg/RobotCommand)')
        self.get_logger().info('Publishing:  /joint_states (sensor_msgs/msg/JointState)')
        self.get_logger().info(f'Rate: {self.publish_rate} Hz, Interpolation: {self.interpolation_speed}')

    def cmd_callback(self, msg: RobotCommand):
        """Callback when Unity sends a RobotCommand."""
        pose = msg.target_pose
        px = pose.position.x
        py = pose.position.y
        pz = pose.position.z
        ox = pose.orientation.x
        oy = pose.orientation.y
        oz = pose.orientation.z
        ow = pose.orientation.w
        self.gripper_open = msg.gripper_state

        self.get_logger().info(
            f'RobotCommand von "{msg.base_id}": '
            f'pos=({px:.4f}, {py:.4f}, {pz:.4f}), '
            f'gripper={"open" if msg.gripper_state else "closed"}'
        )

        success, joints = self.compute_ik(px, py, pz, ox, oy, oz, ow)

        if success:
            self.target_joints = joints
            self.get_logger().info(
                f'IK Loesung: [{joints[0]:.3f}, {joints[1]:.3f}, '
                f'{joints[2]:.3f}, {joints[3]:.3f}] rad'
            )
        else:
            self.get_logger().warn(
                f'IK failed for position ({px:.4f}, {py:.4f}, {pz:.4f})'
            )

    def compute_ik(self, x, y, z, ox, oy, oz, ow):
        """
        Geometric inverse kinematics for 4-DOF robot arm.
        Input: Position in meters (ROS frame), orientation as quaternion.
        Output: (success, [theta1, theta2, theta3, theta4]) in radians.
        """
        theta1 = math.atan2(y, x)
        r = math.sqrt(x * x + y * y)
        z_eff = z - self.BASE_HEIGHT
        pitch = self.quaternion_to_pitch(ox, oy, oz, ow)

        r_wrist = r - self.WRIST_LENGTH * math.cos(pitch)
        z_wrist = z_eff - self.WRIST_LENGTH * math.sin(pitch)

        L1 = self.UPPER_ARM_LENGTH
        L2 = self.FOREARM_LENGTH
        dist_sq = r_wrist * r_wrist + z_wrist * z_wrist
        dist = math.sqrt(dist_sq)

        if dist > (L1 + L2):
            scale = (L1 + L2 - 0.001) / dist
            r_wrist *= scale
            z_wrist *= scale
            dist_sq = r_wrist * r_wrist + z_wrist * z_wrist
            dist = math.sqrt(dist_sq)
            self.get_logger().warn('Target outside workspace - arm fully extended')
        elif dist < 0.001:
            return False, [0.0, 0.0, 0.0, 0.0]

        cos_theta3 = (dist_sq - L1 * L1 - L2 * L2) / (2.0 * L1 * L2)
        cos_theta3 = max(-1.0, min(1.0, cos_theta3))
        theta3 = -math.acos(cos_theta3)

        alpha = math.atan2(z_wrist, r_wrist)
        beta = math.atan2(L2 * math.sin(theta3), L1 + L2 * math.cos(theta3))
        theta2 = alpha + beta
        theta4 = pitch - theta2 - theta3

        joints = [theta1, theta2, theta3, theta4]
        for i in range(4):
            lo, hi = self.JOINT_LIMITS[i]
            joints[i] = max(lo, min(hi, joints[i]))

        return True, joints

    def quaternion_to_pitch(self, x, y, z, w):
        sinp = 2.0 * (w * y - z * x)
        sinp = max(-1.0, min(1.0, sinp))
        return math.asin(sinp)

    def publish_joint_states(self):
        dt = 1.0 / self.publish_rate
        for i in range(4):
            diff = self.target_joints[i] - self.current_joints[i]
            step = self.interpolation_speed * dt
            if abs(diff) < step:
                self.current_joints[i] = self.target_joints[i]
            else:
                self.current_joints[i] += math.copysign(step, diff)

        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'base_link'
        msg.name = self.joint_names
        msg.position = self.current_joints
        msg.velocity = [0.0] * 4
        msg.effort = [0.0] * 4
        self.joint_state_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = RobotMiddlewareNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
