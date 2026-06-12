#!/usr/bin/env python3
"""
unity_moveit_bridge.py — Bridges Unity RobotCommand messages to MoveIt planning.

Uses MoveGroup Action with OMPL planner (position-only IK, no orientation constraint).
Forwards gripper_state, reset, estop commands to /stm32_cmd topic.
plan_only=True: publishes planned trajectory on /planned_trajectory
for stm32_serial_node to execute on real hardware.
"""
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from geometry_msgs.msg import Pose
from moveit_msgs.action import MoveGroup
from moveit_msgs.msg import (PlanningOptions, MotionPlanRequest, Constraints,
                              PositionConstraint, BoundingVolume, RobotState)
from shape_msgs.msg import SolidPrimitive
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectory
from std_msgs.msg import String
from my_robot_interfaces.msg import RobotCommand

class UnityMoveItBridge(Node):
    def __init__(self):
        super().__init__('unity_moveit_bridge')
        
        # Subscribe to Unity messages
        self.subscription = self.create_subscription(
            RobotCommand,
            '/robot_cmd',
            self.command_callback,
            10
        )
        
        # Publisher: planned trajectory → stm32_serial_node
        self.traj_pub = self.create_publisher(JointTrajectory, '/planned_trajectory', 10)

        # Publisher: string commands → stm32_serial_node (/stm32_cmd)
        self.stm32_cmd_pub = self.create_publisher(String, '/stm32_cmd', 10)

        # Action Client for MoveGroup
        self.move_action_client = ActionClient(self, MoveGroup, 'move_action')
        
        # Track last gripper state to detect changes
        self.last_gripper_state = None

        # Subscribe to /joint_states for accurate start state
        self.latest_joint_state = None
        self.create_subscription(JointState, '/joint_states', self.joint_state_callback, 10)

        self.get_logger().info("Waiting for MoveIt Action Server...")
        self.move_action_client.wait_for_server()
        self.get_logger().info("MoveIt Bridge ready! Waiting for commands from Unity...")

    def joint_state_callback(self, msg):
        """Cache latest joint state for use as MoveIt start state."""
        self.latest_joint_state = msg

    def command_callback(self, msg):
        base_id = msg.base_id.strip().upper() if msg.base_id else ""

        # ── Special commands encoded in base_id ─────────────────────
        if base_id == "RESET":
            self.get_logger().info("Reset command received from Unity.")
            cmd = String()
            cmd.data = "reset"
            self.stm32_cmd_pub.publish(cmd)
            return

        if base_id == "ESTOP":
            self.get_logger().warn("Emergency stop received from Unity!")
            cmd = String()
            cmd.data = "estop"
            self.stm32_cmd_pub.publish(cmd)
            return

        if base_id == "HOME":
            self.get_logger().info("Home command received from Unity.")
            cmd = String()
            cmd.data = "home"
            self.stm32_cmd_pub.publish(cmd)
            return

        if base_id == "GRIP_OPEN":
            self.get_logger().info("Gripper OPEN received from Unity.")
            cmd = String()
            cmd.data = "grip_open"
            self.stm32_cmd_pub.publish(cmd)
            return

        if base_id == "GRIP_CLOSE":
            self.get_logger().info("Gripper CLOSE received from Unity.")
            cmd = String()
            cmd.data = "grip_close"
            self.stm32_cmd_pub.publish(cmd)
            return

        # ── Legacy: Gripper state change via gripper_state field ─────
        if self.last_gripper_state is not None and msg.gripper_state != self.last_gripper_state:
            cmd = String()
            cmd.data = "grip_open" if msg.gripper_state else "grip_close"
            self.stm32_cmd_pub.publish(cmd)
            self.get_logger().info(f"Gripper: {'OPEN' if msg.gripper_state else 'CLOSE'}")
        self.last_gripper_state = msg.gripper_state

        # Normal move command -> MoveIt planning
        target_pose = msg.target_pose
        self.get_logger().info(
            f"Target: x={target_pose.position.x:.4f}, "
            f"y={target_pose.position.y:.4f}, "
            f"z={target_pose.position.z:.4f}")
        
        goal_msg = MoveGroup.Goal()
        goal_msg.planning_options = PlanningOptions()
        goal_msg.planning_options.plan_only = True
        goal_msg.planning_options.replan = True
        goal_msg.planning_options.replan_attempts = 3
        
        request = MotionPlanRequest()
        request.workspace_parameters.header.frame_id = "world"
        request.group_name = "arm"
        request.num_planning_attempts = 5
        request.allowed_planning_time = 10.0
        request.max_velocity_scaling_factor = 1.0
        request.max_acceleration_scaling_factor = 1.0

        # Start state from actual robot (is_diff=True: MoveIt fills missing joints)
        if self.latest_joint_state is not None:
            request.start_state = RobotState()
            request.start_state.joint_state = self.latest_joint_state
            request.start_state.is_diff = True
        
        # Position-only constraint (no orientation - 4DOF arm)
        constraint = Constraints()
        pos_constraint = PositionConstraint()
        pos_constraint.header.frame_id = "world"
        pos_constraint.link_name = "tcp_link"
        
        bv = BoundingVolume()
        box = SolidPrimitive()
        box.type = SolidPrimitive.BOX
        box.dimensions = [0.01, 0.01, 0.01]
        bv.primitives.append(box)
        bv.primitive_poses.append(target_pose)
        pos_constraint.constraint_region = bv
        pos_constraint.weight = 1.0
        constraint.position_constraints.append(pos_constraint)
        
        request.goal_constraints.append(constraint)
        goal_msg.request = request
        
        self.get_logger().info("Sending target to MoveIt...")
        future = self.move_action_client.send_goal_async(goal_msg)
        future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error("MoveIt REJECTED the goal!")
            return
        self.get_logger().info("MoveIt ACCEPTED the goal. Waiting for result...")
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self.result_callback)

    def result_callback(self, future):
        result = future.result().result
        status = future.result().status

        if status != 4:
            self.get_logger().error(f"MoveIt planning failed! Status: {status}")
            return

        if (result.planned_trajectory and
                result.planned_trajectory.joint_trajectory and
                len(result.planned_trajectory.joint_trajectory.points) > 0):
            
            traj = result.planned_trajectory.joint_trajectory
            duration = (traj.points[-1].time_from_start.sec +
                        traj.points[-1].time_from_start.nanosec * 1e-9)
            self.get_logger().info(
                f"Trajectory: {len(traj.points)} waypoints, "
                f"duration: {duration:.2f}s, joints: {traj.joint_names}")
            
            start_pos = [f"{p:.3f}" for p in traj.points[0].positions]
            end_pos = [f"{p:.3f}" for p in traj.points[-1].positions]
            self.get_logger().info(f"  Start: {start_pos}")
            self.get_logger().info(f"  End:   {end_pos}")
            
            self.traj_pub.publish(traj)
        else:
            self.get_logger().error("No trajectory in result!")

def main(args=None):
    rclpy.init(args=args)
    node = UnityMoveItBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    rclpy.shutdown()

if __name__ == '__main__':
    main()
