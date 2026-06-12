from std_msgs.msg import Float32
self.servo_pub = self.create_publisher(
        Float32,
        '/inspection_servo_cmd',
        10
    )