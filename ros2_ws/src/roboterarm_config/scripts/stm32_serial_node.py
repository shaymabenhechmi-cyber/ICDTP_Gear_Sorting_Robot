#!/usr/bin/env python3
"""
stm32_serial_node.py — ROS2 bridge between MoveIt trajectories and STM32 motor controller.

Responsibilities:
  - Receives planned trajectories from unity_moveit_bridge (/planned_trajectory)
  - Interpolates waypoints at ~50ms intervals
  - Converts radians → motor steps using calibration config
  - Streams target steps to STM32 via USART2 (USB VCP, 115200 baud)
  - Reads STM32 status frames (5× motor positions + flags)
  - Converts steps → radians + finger interpolation
  - Publishes /joint_states (7 joints: 4 arm + 3 fingers)
  - Handles Reset, Home, Gripper, E-Stop commands via /stm32_cmd topic

Protocol:
  Pi→STM32: 19 bytes  [0xAA, CMD, M1(4B), M2(4B), M3(4B), M4(4B), CRC8]
  STM32→Pi: 23 bytes  [0xBB, FLAGS, M1(4B), M2(4B), M3(4B), M4(4B), M5(4B), CRC8]
"""

import struct
import threading
import time
import math

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectory
from std_msgs.msg import String

try:
    import serial
except ImportError:
    serial = None

# ── Protocol constants ──────────────────────────────────────────────────
START_TX      = 0xAA   # Pi → STM32
START_RX      = 0xBB   # STM32 → Pi
TX_FRAME_SIZE = 19
RX_FRAME_SIZE = 23

CMD_STREAM_POS  = 0x01
CMD_RESET       = 0x02
CMD_HOME        = 0x03
CMD_GRIP_OPEN   = 0x04
CMD_GRIP_CLOSE  = 0x05
CMD_ESTOP       = 0x06

# Status flag bits
FLAG_M1_MOVING   = (1 << 0)
FLAG_M2_MOVING   = (1 << 1)
FLAG_M3_MOVING   = (1 << 2)
FLAG_M4_MOVING   = (1 << 3)
FLAG_M5_MOVING   = (1 << 4)
FLAG_M5_STALL    = (1 << 5)
FLAG_HOMING_DONE = (1 << 6)
FLAG_ERROR       = (1 << 7)


def crc8_xor(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
    return crc


class STM32SerialNode(Node):
    def __init__(self):
        super().__init__('stm32_serial_node')

        # ── Parameters ──────────────────────────────────────────────────
        self.declare_parameter('serial_port', '/dev/ttyACM0')
        self.declare_parameter('baud_rate', 115200)
        self.declare_parameter('report_interval_ms', 50)

        # Joint config: name → {motor_index, steps_per_rad, offset_steps}
        # All values loaded from stm32_calibration.yaml via launch file
        for jname in ['joint_basis_arm1', 'joint_arm1_arm2',
                       'joint_arm2_arm3', 'joint_arm3_greifer']:
            self.declare_parameter(f'joints.{jname}.motor_index')
            self.declare_parameter(f'joints.{jname}.steps_per_rad')
            self.declare_parameter(f'joints.{jname}.offset_steps')

        # Gripper config
        self.declare_parameter('gripper.motor_index')
        self.declare_parameter('gripper.steps_open')
        self.declare_parameter('gripper.steps_closed')

        # Finger mapping: joint → {open, closed}
        for fname in ['joint_greifer_finger1', 'joint_greifer_finger2',
                       'joint_greifer_finger3']:
            self.declare_parameter(f'gripper.finger_mapping.{fname}.open')
            self.declare_parameter(f'gripper.finger_mapping.{fname}.closed')

        # ── Load config ─────────────────────────────────────────────────
        self.serial_port = self.get_parameter('serial_port').value
        self.baud_rate = self.get_parameter('baud_rate').value
        self.report_interval = self.get_parameter('report_interval_ms').value / 1000.0

        # Build joint config lookup
        self.arm_joints = ['joint_basis_arm1', 'joint_arm1_arm2',
                           'joint_arm2_arm3', 'joint_arm3_greifer']
        self.joint_config = {}
        for jname in self.arm_joints:
            self.joint_config[jname] = {
                'motor_index': self.get_parameter(f'joints.{jname}.motor_index').value,
                'steps_per_rad': self.get_parameter(f'joints.{jname}.steps_per_rad').value,
                'offset_steps': self.get_parameter(f'joints.{jname}.offset_steps').value,
            }

        self.gripper_steps_open = self.get_parameter('gripper.steps_open').value
        self.gripper_steps_closed = self.get_parameter('gripper.steps_closed').value

        self.finger_joints = ['joint_greifer_finger1',
                              'joint_greifer_finger2', 'joint_greifer_finger3']
        self.finger_config = {}
        for fj in self.finger_joints:
            self.finger_config[fj] = {
                'open': self.get_parameter(f'gripper.finger_mapping.{fj}.open').value,
                'closed': self.get_parameter(f'gripper.finger_mapping.{fj}.closed').value,
            }

        # ── State ───────────────────────────────────────────────────────
        self.ser = None
        self.connected = False
        self.lock = threading.Lock()

        # Current motor positions from STM32 feedback (steps)
        self.motor_positions = [0, 0, 0, 0, 0]  # M1..M5
        self.status_flags = 0
        self.received_first_feedback = False

        # Gripper state tracking
        self.gripper_is_open = True       # After reset/home gripper is always open
        self.last_gripper_direction = None  # 'open' or 'close' — last command sent

        # Trajectory interpolation state
        self.trajectory = None
        self.traj_start_time = None
        self.traj_joint_names = []
        self.traj_lock = threading.Lock()

        # ── Publishers ──────────────────────────────────────────────────
        self.joint_state_pub = self.create_publisher(JointState, '/joint_states', 10)

        # ── Subscribers ─────────────────────────────────────────────────
        self.create_subscription(
            JointTrajectory, '/planned_trajectory',
            self.trajectory_callback, 10)

        self.create_subscription(
            String, '/stm32_cmd',
            self.cmd_callback, 10)

        # ── Serial connection ───────────────────────────────────────────
        self.connect_serial()

        # ── Send initial RESET to get STM32 into known state ────────────
        if self.connected:
            time.sleep(1.0)  # Wait for STM32 boot
            self.send_frame(CMD_RESET)
            self.get_logger().info('Initial RESET sent to STM32.')

        # ── RX thread ───────────────────────────────────────────────────
        self.rx_thread = threading.Thread(target=self.serial_rx_loop, daemon=True)
        self.rx_thread.start()

        # ── Main loop timer (50ms) ──────────────────────────────────────
        self.timer = self.create_timer(self.report_interval, self.main_loop)

        # Debug logging: throttle counter (log every N-th main_loop call)
        self.debug_log_counter = 0
        self.debug_log_interval = 200  # every 200th call = ~1s at 5ms

        self.get_logger().info(
            f'STM32 Serial Node started. Port={self.serial_port}, Baud={self.baud_rate}')

        # ── Log calibration config at startup ───────────────────────────
        for jname in self.arm_joints:
            cfg = self.joint_config[jname]
            spr = cfg['steps_per_rad']
            off = cfg['offset_steps']
            steps_per_rev = abs(spr) * 2.0 * math.pi
            self.get_logger().info(
                f'[CONFIG] {jname}: steps_per_rad={spr:.1f}, offset={off}, '
                f'steps/rev={steps_per_rev:.0f}, sign={"NEG" if spr < 0 else "POS"}')

    # ════════════════════════════════════════════════════════════════════
    #  Serial Connection
    # ════════════════════════════════════════════════════════════════════

    def connect_serial(self):
        if serial is None:
            self.get_logger().error('pyserial not installed! pip install pyserial')
            return

        try:
            self.ser = serial.Serial(
                port=self.serial_port,
                baudrate=self.baud_rate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1
            )
            self.connected = True
            self.get_logger().info(f'Serial connected: {self.serial_port}')
        except serial.SerialException as e:
            self.get_logger().warn(f'Serial not connected: {e}. Retrying...')
            self.connected = False

    # ════════════════════════════════════════════════════════════════════
    #  Serial TX: Send 19-byte command frame
    # ════════════════════════════════════════════════════════════════════

    def send_frame(self, cmd_id: int, m1=0, m2=0, m3=0, m4=0):
        """Build and send a 19-byte command frame to STM32."""
        payload = struct.pack('<Biiii', cmd_id, m1, m2, m3, m4)
        # payload is 17 bytes (1 + 4*4)
        crc = crc8_xor(payload)
        frame = bytes([START_TX]) + payload + bytes([crc])
        assert len(frame) == TX_FRAME_SIZE

        with self.lock:
            if self.connected and self.ser and self.ser.is_open:
                try:
                    self.ser.write(frame)
                except serial.SerialException as e:
                    self.get_logger().error(f'TX error: {e}')
                    self.connected = False

    # ════════════════════════════════════════════════════════════════════
    #  Serial RX: Read 23-byte status frames in background thread
    # ════════════════════════════════════════════════════════════════════

    def serial_rx_loop(self):
        """Background thread: continuously reads STM32 status frames."""
        while rclpy.ok():
            if not self.connected or self.ser is None:
                # Try reconnect
                time.sleep(2.0)
                self.connect_serial()
                continue

            try:
                # Synchronize: read until we find START_RX byte
                b = self.ser.read(1)
                if len(b) == 0:
                    continue
                if b[0] != START_RX:
                    continue

                # Read remaining 22 bytes
                rest = self.ser.read(RX_FRAME_SIZE - 1)
                if len(rest) != RX_FRAME_SIZE - 1:
                    continue

                frame = bytes([START_RX]) + rest

                # Validate CRC (bytes 1..21)
                crc = crc8_xor(frame[1:RX_FRAME_SIZE - 1])
                if crc != frame[RX_FRAME_SIZE - 1]:
                    continue

                # Parse
                flags = frame[1]
                m1 = struct.unpack_from('<i', frame, 2)[0]
                m2 = struct.unpack_from('<i', frame, 6)[0]
                m3 = struct.unpack_from('<i', frame, 10)[0]
                m4 = struct.unpack_from('<i', frame, 14)[0]
                m5 = struct.unpack_from('<i', frame, 18)[0]

                self.motor_positions = [m1, m2, m3, m4, m5]
                self.status_flags = flags
                self.received_first_feedback = True

                # ── Update gripper state from STM32 flags ───────────
                m5_moving = bool(flags & FLAG_M5_MOVING)

                if not m5_moving and self.last_gripper_direction is not None:
                    # Motor stopped after a gripper command → adopt as state
                    if self.last_gripper_direction == 'close':
                        self.gripper_is_open = False
                    elif self.last_gripper_direction == 'open':
                        self.gripper_is_open = True
                    self.last_gripper_direction = None  # Consumed

            except serial.SerialException as e:
                self.get_logger().error(f'RX error: {e}')
                self.connected = False
            except Exception as e:
                self.get_logger().error(f'RX unknown error: {e}')

    # ════════════════════════════════════════════════════════════════════
    #  Conversion: steps ↔ radians
    # ════════════════════════════════════════════════════════════════════

    # Joint position limits (rad) — safety clamp before sending to STM32
    JOINT_LIMITS = {
        'joint_basis_arm1':   (-6.17, 0.0),
        'joint_arm1_arm2':    (-2.04, 0.0),
        'joint_arm2_arm3':    (-2.42, 0.0),
        'joint_arm3_greifer': (-1.57, 1.57),
    }

    def rad_to_steps(self, joint_name: str, rad: float) -> int:
        cfg = self.joint_config[joint_name]
        # Safety clamp to joint limits
        if joint_name in self.JOINT_LIMITS:
            lo, hi = self.JOINT_LIMITS[joint_name]
            rad = max(lo, min(hi, rad))
        return int(round(rad * cfg['steps_per_rad'] + cfg['offset_steps']))

    def steps_to_rad(self, joint_name: str, steps: int) -> float:
        cfg = self.joint_config[joint_name]
        return (steps - cfg['offset_steps']) / cfg['steps_per_rad']

    def gripper_progress(self) -> float:
        """Return 0.0 (open) .. 1.0 (closed) based on M5 step position."""
        m5 = self.motor_positions[4]
        range_steps = self.gripper_steps_closed - self.gripper_steps_open
        if range_steps == 0:
            return 0.0
        progress = (m5 - self.gripper_steps_open) / range_steps
        return max(0.0, min(1.0, progress))

    def finger_value(self, joint_name: str, progress: float) -> float:
        """Interpolate finger joint value from open to closed based on progress."""
        cfg = self.finger_config[joint_name]
        return cfg['open'] + progress * (cfg['closed'] - cfg['open'])

    # ════════════════════════════════════════════════════════════════════
    #  Publish /joint_states
    # ════════════════════════════════════════════════════════════════════

    def publish_joint_states(self):
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()

        progress = self.gripper_progress()

        # 4 arm joints
        names = list(self.arm_joints)
        positions = []
        for i, jname in enumerate(self.arm_joints):
            positions.append(self.steps_to_rad(jname, self.motor_positions[i]))

        # 4 gripper/finger joints
        for fj in self.finger_joints:
            names.append(fj)
            positions.append(self.finger_value(fj, progress))

        msg.name = names
        msg.position = positions
        msg.velocity = [0.0] * len(names)
        msg.effort = [0.0] * len(names)

        self.joint_state_pub.publish(msg)

    # ════════════════════════════════════════════════════════════════════
    #  Trajectory interpolation
    # ════════════════════════════════════════════════════════════════════

    def trajectory_callback(self, msg: JointTrajectory):
        """Receive a planned trajectory and start executing it."""
        if len(msg.points) == 0:
            self.get_logger().warn('Empty trajectory received.')
            return

        with self.traj_lock:
            self.trajectory = msg
            self.traj_start_time = time.monotonic()
            self.traj_joint_names = list(msg.joint_names)

        self.get_logger().info(
            f'Trajectory received: {len(msg.points)} waypoints, '
            f'duration: {msg.points[-1].time_from_start.sec + msg.points[-1].time_from_start.nanosec*1e-9:.2f}s')

        # Debug: log start and end positions with step conversions
        start_pos = msg.points[0].positions
        end_pos = msg.points[-1].positions
        joint_names = list(msg.joint_names)
        self.get_logger().info(f'[TRAJ] Joint order: {joint_names}')
        for j, jname in enumerate(joint_names):
            if jname in self.joint_config:
                s_start = self.rad_to_steps(jname, start_pos[j])
                s_end = self.rad_to_steps(jname, end_pos[j])
                cfg = self.joint_config[jname]
                self.get_logger().info(
                    f'[TRAJ] {jname}: Start={start_pos[j]:+.4f}rad ({math.degrees(start_pos[j]):+.1f}°) → {s_start} steps | '
                    f'End={end_pos[j]:+.4f}rad ({math.degrees(end_pos[j]):+.1f}°) → {s_end} steps | '
                    f'Δrad={end_pos[j]-start_pos[j]:+.4f} Δsteps={s_end-s_start}')

    def interpolate_trajectory(self) -> dict:
        """Return current target joint angles (rad) from trajectory, or None if idle."""
        with self.traj_lock:
            if self.trajectory is None or self.traj_start_time is None:
                return None

            elapsed = time.monotonic() - self.traj_start_time
            points = self.trajectory.points
            joint_names = self.traj_joint_names

            # Convert all timestamps to float seconds
            times = []
            for pt in points:
                t = pt.time_from_start.sec + pt.time_from_start.nanosec * 1e-9
                times.append(t)

            # Past last waypoint → trajectory complete
            if elapsed >= times[-1]:
                result = {}
                for j, name in enumerate(joint_names):
                    result[name] = points[-1].positions[j]
                self.trajectory = None
                self.traj_start_time = None
                self.get_logger().info('Trajectory completed.')
                return result

            # Find the two bounding waypoints
            idx = 0
            for i in range(len(times) - 1):
                if times[i] <= elapsed <= times[i + 1]:
                    idx = i
                    break

            # Linear interpolation between waypoints
            t0 = times[idx]
            t1 = times[idx + 1]
            alpha = (elapsed - t0) / (t1 - t0) if (t1 - t0) > 0 else 1.0

            result = {}
            for j, name in enumerate(joint_names):
                p0 = points[idx].positions[j]
                p1 = points[idx + 1].positions[j]
                result[name] = p0 + alpha * (p1 - p0)

            return result

    # ════════════════════════════════════════════════════════════════════
    #  Command callback (/stm32_cmd topic)
    # ════════════════════════════════════════════════════════════════════

    def cmd_callback(self, msg: String):
        """Handle string commands: 'reset', 'home', 'grip_open', 'grip_close', 'estop'."""
        cmd = msg.data.strip().lower()

        if cmd == 'reset':
            self.get_logger().info('Sending RESET (StallGuard homing)...')
            self.gripper_is_open = True
            self.last_gripper_direction = None
            self.send_frame(CMD_RESET)
        elif cmd == 'estop':
            self.get_logger().warn('Sending EMERGENCY STOP!')
            self.send_frame(CMD_ESTOP)
        elif cmd == 'grip_open':
            if self.gripper_is_open:
                self.get_logger().info('Gripper already open — ignored.')
                return
            self.get_logger().info('Sending gripper OPEN...')
            self.last_gripper_direction = 'open'
            self.send_frame(CMD_GRIP_OPEN)
        elif cmd == 'grip_close':
            if not self.gripper_is_open:
                self.get_logger().info('Gripper already closed — ignored.')
                return
            self.get_logger().info('Sending gripper CLOSE...')
            self.last_gripper_direction = 'close'
            self.send_frame(CMD_GRIP_CLOSE)
        elif cmd.startswith('home'):
            # home [s1 s2 s3 s4] — optional step values
            parts = cmd.split()
            if len(parts) == 5:
                steps = [int(parts[i]) for i in range(1, 5)]
            else:
                # Default home position (all zero = homing position)
                steps = [0, 0, 0, 0]
            self.get_logger().info(f'Sending HOME: {steps}')
            self.gripper_is_open = True
            self.last_gripper_direction = None
            self.send_frame(CMD_HOME, *steps)
        else:
            self.get_logger().warn(f'Unknown command: {cmd}')

    # ════════════════════════════════════════════════════════════════════
    #  Main loop timer (~50ms)
    # ════════════════════════════════════════════════════════════════════

    def main_loop(self):
        """Called every ~50ms by ROS2 timer."""

        # Always publish joint states so MoveIt has a valid start state.
        # Before STM32 feedback arrives, positions default to 0.0 rad.
        self.publish_joint_states()

        # Don't stream trajectory until we have real data from STM32
        if not self.received_first_feedback:
            return

        # 1. Interpolate trajectory and stream target steps
        target = self.interpolate_trajectory()
        if target is not None:
            steps = [0, 0, 0, 0]
            for jname in self.arm_joints:
                if jname in target:
                    idx = self.joint_config[jname]['motor_index']
                    steps[idx] = self.rad_to_steps(jname, target[jname])
            self.send_frame(CMD_STREAM_POS, *steps)

            # Debug logging (throttled)
            self.debug_log_counter += 1
            if self.debug_log_counter % self.debug_log_interval == 1:
                for jname in self.arm_joints:
                    if jname in target:
                        cfg = self.joint_config[jname]
                        idx = cfg['motor_index']
                        rad_val = target[jname]
                        target_steps = steps[idx]
                        fb_steps = self.motor_positions[idx]
                        fb_rad = self.steps_to_rad(jname, fb_steps)
                        delta = target_steps - fb_steps
                        self.get_logger().info(
                            f'[STREAM] {jname}: '
                            f'MoveIt={rad_val:+.4f}rad ({math.degrees(rad_val):+.1f}°) → '
                            f'target={target_steps} steps | '
                            f'STM32_pos={fb_steps} steps ({fb_rad:+.4f}rad / {math.degrees(fb_rad):+.1f}°) | '
                            f'delta={delta}')


def main(args=None):
    rclpy.init(args=args)
    node = STM32SerialNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node.ser and node.ser.is_open:
            node.ser.close()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
