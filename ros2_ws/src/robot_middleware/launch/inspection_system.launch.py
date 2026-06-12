from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():

    return LaunchDescription([

        # ─────────────────────────────
        # Platform servo controller
        # ─────────────────────────────
        Node(
            package='robot_middleware',
            executable='platform_state_node',
            name='platform_state_node',
            output='screen'
        ),

        # ─────────────────────────────
        # Inspection brain
        # ─────────────────────────────
        Node(
            package='robot_middleware',
            executable='inspection_node',
            name='inspection_node',
            output='screen'
        ),

        # ─────────────────────────────
        # Robot execution layer
        # (IMPORTANT: only needed if you convert it to node later)
        # ─────────────────────────────
        # Node(
        #     package='robot_middleware',
        #     executable='move_robot_node',
        #     name='robot_mover',
        #     output='screen'
        # ),
    ])