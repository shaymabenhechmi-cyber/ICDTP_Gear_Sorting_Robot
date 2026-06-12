// generated from rosidl_generator_cpp/resource/idl__builder.hpp.em
// with input from my_robot_interfaces:msg/RobotCommand.idl
// generated code does not contain a copyright notice

// IWYU pragma: private, include "my_robot_interfaces/msg/robot_command.hpp"


#ifndef MY_ROBOT_INTERFACES__MSG__DETAIL__ROBOT_COMMAND__BUILDER_HPP_
#define MY_ROBOT_INTERFACES__MSG__DETAIL__ROBOT_COMMAND__BUILDER_HPP_

#include <algorithm>
#include <utility>

#include "my_robot_interfaces/msg/detail/robot_command__struct.hpp"
#include "rosidl_runtime_cpp/message_initialization.hpp"


namespace my_robot_interfaces
{

namespace msg
{

namespace builder
{

class Init_RobotCommand_gripper_state
{
public:
  explicit Init_RobotCommand_gripper_state(::my_robot_interfaces::msg::RobotCommand & msg)
  : msg_(msg)
  {}
  ::my_robot_interfaces::msg::RobotCommand gripper_state(::my_robot_interfaces::msg::RobotCommand::_gripper_state_type arg)
  {
    msg_.gripper_state = std::move(arg);
    return std::move(msg_);
  }

private:
  ::my_robot_interfaces::msg::RobotCommand msg_;
};

class Init_RobotCommand_target_pose
{
public:
  explicit Init_RobotCommand_target_pose(::my_robot_interfaces::msg::RobotCommand & msg)
  : msg_(msg)
  {}
  Init_RobotCommand_gripper_state target_pose(::my_robot_interfaces::msg::RobotCommand::_target_pose_type arg)
  {
    msg_.target_pose = std::move(arg);
    return Init_RobotCommand_gripper_state(msg_);
  }

private:
  ::my_robot_interfaces::msg::RobotCommand msg_;
};

class Init_RobotCommand_base_id
{
public:
  Init_RobotCommand_base_id()
  : msg_(::rosidl_runtime_cpp::MessageInitialization::SKIP)
  {}
  Init_RobotCommand_target_pose base_id(::my_robot_interfaces::msg::RobotCommand::_base_id_type arg)
  {
    msg_.base_id = std::move(arg);
    return Init_RobotCommand_target_pose(msg_);
  }

private:
  ::my_robot_interfaces::msg::RobotCommand msg_;
};

}  // namespace builder

}  // namespace msg

template<typename MessageType>
auto build();

template<>
inline
auto build<::my_robot_interfaces::msg::RobotCommand>()
{
  return my_robot_interfaces::msg::builder::Init_RobotCommand_base_id();
}

}  // namespace my_robot_interfaces

#endif  // MY_ROBOT_INTERFACES__MSG__DETAIL__ROBOT_COMMAND__BUILDER_HPP_
