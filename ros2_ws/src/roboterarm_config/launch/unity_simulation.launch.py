import os
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource, AnyLaunchDescriptionSource
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    rosbridge_dir = get_package_share_directory('rosbridge_server')
    roboterarm_config_dir = get_package_share_directory('roboterarm_config')

    calibration_file = os.path.join(
        roboterarm_config_dir, 'config', 'stm32_calibration.yaml'
    )

    # 1. rosbridge WebSocket Server (interface to Unity)
    rosbridge_launch = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(
            os.path.join(rosbridge_dir, 'launch', 'rosbridge_websocket_launch.xml')
        ),
        launch_arguments={'port': '9090'}.items()
    )

    # 2. Robot State Publisher (URDF -> /robot_description, /tf)
    rsp_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(roboterarm_config_dir, 'launch', 'rsp.launch.py')
        )
    )

    # 3. Statische TF: world -> base_link
    static_tf_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(roboterarm_config_dir, 'launch',
                         'static_virtual_joint_tfs.launch.py')
        )
    )

    # 4. MoveIt move_group (planning, IK, OMPL)
    move_group_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(roboterarm_config_dir, 'launch', 'move_group.launch.py')
        )
    )

    # 5. Unity <-> MoveIt Bridge
    unity_bridge_node = Node(
        package='roboterarm_config',
        executable='unity_moveit_bridge.py',
        output='screen'
    )

    # 6. STM32 Serial Bridge — ONLY /joint_states publisher
    stm32_serial_node = Node(
        package='roboterarm_config',
        executable='stm32_serial_node.py',
        output='screen',
        parameters=[
            calibration_file,
            {'serial_port': '/dev/ttyACM0'},
            {'baud_rate': 115200},
        ]
    )

    return LaunchDescription([
        rosbridge_launch,
        rsp_launch,
        static_tf_launch,
        move_group_launch,
        # Wait until MoveIt is fully started
        TimerAction(period=12.0, actions=[
            unity_bridge_node,
            stm32_serial_node,
        ])
    ])
