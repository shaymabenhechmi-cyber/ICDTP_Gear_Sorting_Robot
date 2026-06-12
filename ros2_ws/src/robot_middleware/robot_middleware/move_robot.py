#!/usr/bin/env python3
import rclpy
import time
from rclpy.node import Node
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from sensor_msgs.msg import JointState
from std_msgs.msg import String


class RobotMover(Node):

    def __init__(self):
        super().__init__('robot_mover')

        self.traj_pub = self.create_publisher(JointTrajectory, '/planned_trajectory', 10)
        self.cmd_pub  = self.create_publisher(String, '/stm32_cmd', 10)

        self.joint_names = [
            'joint_basis_arm1',
            'joint_arm1_arm2',
            'joint_arm2_arm3',
            'joint_arm3_greifer'
        ]

        self.current_positions = [0.0, 0.0, 0.0, 0.0]
        self.create_subscription(JointState, '/joint_states', self._joint_state_cb, 10)

        # ── Wait for publishers to connect ─────────────────────────
        self._wait_for_connection()

    # ─────────────────────────────────────────────────────────────
    # Connection
    # ─────────────────────────────────────────────────────────────
    def _wait_for_connection(self):
        """Spin until both publishers have at least one subscriber."""
        self.get_logger().info("Waiting for subscribers to connect...")
        start = time.time()
        while True:
            rclpy.spin_once(self, timeout_sec=0.1)
            traj_ready = self.traj_pub.get_subscription_count() > 0
            cmd_ready  = self.cmd_pub.get_subscription_count() > 0
            if traj_ready and cmd_ready:
                self.get_logger().info("Publishers connected.")
                break
            if time.time() - start > 10.0:
                self.get_logger().warn("Timeout waiting for subscribers — continuing anyway.")
                break

    # ─────────────────────────────────────────────────────────────
    # Joint state callback
    # ─────────────────────────────────────────────────────────────
    def _joint_state_cb(self, msg: JointState):
        pos_map = dict(zip(msg.name, msg.position))
        self.current_positions = [pos_map.get(n, 0.0) for n in self.joint_names]

    # ─────────────────────────────────────────────────────────────
    # Wait for motion to finish (time-based)
    # ─────────────────────────────────────────────────────────────
    def wait_for_motion(self, duration=3.5):
        self.get_logger().info(f"Waiting {duration}s for motion to complete...")
        start = time.time()
        while time.time() - start < duration:
            rclpy.spin_once(self, timeout_sec=0.1)
        self.get_logger().info(f"Motion done. Position: {self.current_positions}")

    # ─────────────────────────────────────────────────────────────
    # Core helpers
    # ─────────────────────────────────────────────────────────────
    def send_trajectory(self, waypoints: list, duration_sec=2):
        """
        waypoints: list of position lists.
        First point is always current position (auto-added).
        Time is spread evenly: duration_sec per segment.
        """
        points = []

        # p0 = current position
        p0 = JointTrajectoryPoint()
        p0.positions = list(self.current_positions)
        p0.time_from_start.sec = 0
        points.append(p0)

        # remaining waypoints
        for i, pos in enumerate(waypoints):
            p = JointTrajectoryPoint()
            p.positions = pos
            p.time_from_start.sec = duration_sec * (i + 1)
            points.append(p)

        traj = JointTrajectory()
        traj.joint_names = self.joint_names
        traj.points = points

        self.traj_pub.publish(traj)
        self.get_logger().info(f"Trajectory: {len(points)} waypoints")
        for pt in points:
            self.get_logger().info(f"  → {list(pt.positions)}")

    def send_gripper(self, state: str):
        msg = String()
        msg.data = state
        self.cmd_pub.publish(msg)
        self.get_logger().info(f"Gripper: {state}")

    # ─────────────────────────────────────────────────────────────
    # Lift helper
    # ─────────────────────────────────────────────────────────────
    def _lift_positions(self, base_positions):
        """Keep joints 0 and 3, lift joints 1 and 2 to safe height."""
        lifted = list(base_positions)
        lifted[1] = -0.5
        lifted[2] = -0.5
        return lifted

    # ─────────────────────────────────────────────────────────────
    # High-level motions
    # ─────────────────────────────────────────────────────────────
    def move_to_station(self):
        """Lift → rotate to station → lower → grip close."""
        self.get_logger().info("Moving to INSPECTION STATION")
        target = [-3.5, -1.0, -1.0, 0.0]   # TODO: tune
        cur    = self.current_positions

        self.send_trajectory([
            [cur[0],    -0.5, -0.5, cur[3]   ],   # 1. lift joints 1&2
            [target[0], -0.5, -0.5, target[3]],   # 2. rotate base to station
            target                                  # 3. lower to station
        ], duration_sec=2)

        self.wait_for_motion(6.5)
        self.send_gripper("grip_close")

    def move_robot_to_good_bin(self):
        """Lift → rotate to good bin → lower → grip open."""
        self.get_logger().info("Moving to GOOD bin")
        target = [-5.0, -1.0, -0.8, 0.0]   # TODO: tune
        cur    = self.current_positions

        self.send_trajectory([
            [cur[0],    -0.5, -0.5, cur[3]   ],   # 1. lift joints 1&2
            [target[0], -0.5, -0.5, target[3]],   # 2. rotate base to good bin
            target                                  # 3. lower to good bin
        ], duration_sec=2)

        self.wait_for_motion(6.5)
        self.send_gripper("grip_open")

    def move_robot_to_reject_bin(self):
        """Lift → rotate to reject bin → lower → grip open."""
        self.get_logger().info("Moving to REJECT bin")
        target = [-5.5, -1.0, -0.9, -0.5]  # TODO: tune
        cur    = self.current_positions

        self.send_trajectory([
            [cur[0],    -0.5, -0.5, cur[3]   ],   # 1. lift joints 1&2
            [target[0], -0.5, -0.5, target[3]],   # 2. rotate base to reject bin
            target                                  # 3. lower to reject bin
        ], duration_sec=2)

        self.wait_for_motion(6.5)
        self.send_gripper("grip_open")


# ── Global helpers ─────────────────────────────────────────────
_node = None

def _get_node():
    global _node
    if _node is None:
        rclpy.init(args=None)
        _node = RobotMover()
    return _node

def move_to_station():
    _get_node().move_to_station()

def move_robot_to_good_bin():
    _get_node().move_robot_to_good_bin()

def move_robot_to_reject_bin():
    _get_node().move_robot_to_reject_bin()