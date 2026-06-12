from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    port_arg = DeclareLaunchArgument(
        'port', default_value='9090',
        description='WebSocket port for rosbridge'
    )
    publish_rate_arg = DeclareLaunchArgument(
        'publish_rate', default_value='50.0',
        description='Joint state publish rate in Hz'
    )
    interpolation_speed_arg = DeclareLaunchArgument(
        'interpolation_speed', default_value='2.0',
        description='Joint interpolation speed factor'
    )

    rosbridge_node = Node(
        package='rosbridge_server',
        executable='rosbridge_websocket',
        name='rosbridge_websocket',
        output='screen',
        parameters=[{
            'port': LaunchConfiguration('port'),
            'address': '',
            'retry_startup_delay': 1.0,
            'fragment_timeout': 600,
            'delay_between_messages': 0.0,
            'max_message_size': 10000000,
            'unregister_timeout': 10.0,
        }]
    )

    middleware_node = Node(
        package='robot_middleware',
        executable='robot_middleware_node',
        name='robot_middleware_node',
        output='screen',
        parameters=[{
            'publish_rate': LaunchConfiguration('publish_rate'),
            'interpolation_speed': LaunchConfiguration('interpolation_speed'),
        }]
    )

    return LaunchDescription([
        port_arg,
        publish_rate_arg,
        interpolation_speed_arg,
        LogInfo(msg='=== Robot Middleware Launch ==='),
        LogInfo(msg='Rosbridge WebSocket auf Port 9090...'),
        LogInfo(msg='Middleware: /robot_cmd -> IK -> /joint_states'),
        rosbridge_node,
        middleware_node,
    ])
