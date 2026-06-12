#!/usr/bin/env python3
import rclpy
import time
from move_robot import RobotMover

def main():
    rclpy.init()
    node = RobotMover()  # already waits for subscribers inside __init__

    # ── Wait for first /joint_states ───────────────────────────────
    print("Waiting for joint states...")
    start = time.time()
    while time.time() - start < 3.0:
        rclpy.spin_once(node, timeout_sec=0.1)
        if node.current_positions != [0.0, 0.0, 0.0, 0.0]:
            print(f"✓ Current position: {node.current_positions}")
            break
    else:
        print("WARNING: No joint states received, starting from [0,0,0,0]")

    # ── Test 0: Move to station ────────────────────────────────────
    print("\n[1/4] Moving to inspection station...")
    node.move_to_station()
    print(f"✓ At station. Position: {node.current_positions}")

    # ── Test 1: Good bin ───────────────────────────────────────────
    print("\n[2/4] Moving to GOOD bin...")
    node.move_robot_to_good_bin()
    print(f"✓ At good bin. Position: {node.current_positions}")

    # ── Test 2: Back to station ────────────────────────────────────
    print("\n[3/4] Back to inspection station...")
    node.move_to_station()
    print(f"✓ At station. Position: {node.current_positions}")

    # ── Test 3: Reject bin ─────────────────────────────────────────
    print("\n[4/4] Moving to REJECT bin...")
    node.move_robot_to_reject_bin()
    print(f"✓ At reject bin. Position: {node.current_positions}")

    print("\n✓ All tests complete!")
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()