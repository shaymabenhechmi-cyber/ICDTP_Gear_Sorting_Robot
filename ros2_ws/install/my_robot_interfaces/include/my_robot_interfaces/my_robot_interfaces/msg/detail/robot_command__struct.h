// generated from rosidl_generator_c/resource/idl__struct.h.em
// with input from my_robot_interfaces:msg/RobotCommand.idl
// generated code does not contain a copyright notice

// IWYU pragma: private, include "my_robot_interfaces/msg/robot_command.h"


#ifndef MY_ROBOT_INTERFACES__MSG__DETAIL__ROBOT_COMMAND__STRUCT_H_
#define MY_ROBOT_INTERFACES__MSG__DETAIL__ROBOT_COMMAND__STRUCT_H_

#ifdef __cplusplus
extern "C"
{
#endif

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// Constants defined in the message

// Include directives for member types
// Member 'base_id'
#include "rosidl_runtime_c/string.h"
// Member 'target_pose'
#include "geometry_msgs/msg/detail/pose__struct.h"

/// Struct defined in msg/RobotCommand in the package my_robot_interfaces.
/**
  * Soll-Pose des Roboter-TCP von Unity
 */
typedef struct my_robot_interfaces__msg__RobotCommand
{
  rosidl_runtime_c__String base_id;
  geometry_msgs__msg__Pose target_pose;
  bool gripper_state;
} my_robot_interfaces__msg__RobotCommand;

// Struct for a sequence of my_robot_interfaces__msg__RobotCommand.
typedef struct my_robot_interfaces__msg__RobotCommand__Sequence
{
  my_robot_interfaces__msg__RobotCommand * data;
  /// The number of valid items in data
  size_t size;
  /// The number of allocated items in data
  size_t capacity;
} my_robot_interfaces__msg__RobotCommand__Sequence;

#ifdef __cplusplus
}
#endif

#endif  // MY_ROBOT_INTERFACES__MSG__DETAIL__ROBOT_COMMAND__STRUCT_H_
