// generated from rosidl_generator_c/resource/idl__functions.c.em
// with input from my_robot_interfaces:msg/RobotCommand.idl
// generated code does not contain a copyright notice
#include "my_robot_interfaces/msg/detail/robot_command__functions.h"

#include <assert.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

#include "rcutils/allocator.h"


// Include directives for member types
// Member `base_id`
#include "rosidl_runtime_c/string_functions.h"
// Member `target_pose`
#include "geometry_msgs/msg/detail/pose__functions.h"

bool
my_robot_interfaces__msg__RobotCommand__init(my_robot_interfaces__msg__RobotCommand * msg)
{
  if (!msg) {
    return false;
  }
  // base_id
  if (!rosidl_runtime_c__String__init(&msg->base_id)) {
    my_robot_interfaces__msg__RobotCommand__fini(msg);
    return false;
  }
  // target_pose
  if (!geometry_msgs__msg__Pose__init(&msg->target_pose)) {
    my_robot_interfaces__msg__RobotCommand__fini(msg);
    return false;
  }
  // gripper_state
  return true;
}

void
my_robot_interfaces__msg__RobotCommand__fini(my_robot_interfaces__msg__RobotCommand * msg)
{
  if (!msg) {
    return;
  }
  // base_id
  rosidl_runtime_c__String__fini(&msg->base_id);
  // target_pose
  geometry_msgs__msg__Pose__fini(&msg->target_pose);
  // gripper_state
}

bool
my_robot_interfaces__msg__RobotCommand__are_equal(const my_robot_interfaces__msg__RobotCommand * lhs, const my_robot_interfaces__msg__RobotCommand * rhs)
{
  if (!lhs || !rhs) {
    return false;
  }
  // base_id
  if (!rosidl_runtime_c__String__are_equal(
      &(lhs->base_id), &(rhs->base_id)))
  {
    return false;
  }
  // target_pose
  if (!geometry_msgs__msg__Pose__are_equal(
      &(lhs->target_pose), &(rhs->target_pose)))
  {
    return false;
  }
  // gripper_state
  if (lhs->gripper_state != rhs->gripper_state) {
    return false;
  }
  return true;
}

bool
my_robot_interfaces__msg__RobotCommand__copy(
  const my_robot_interfaces__msg__RobotCommand * input,
  my_robot_interfaces__msg__RobotCommand * output)
{
  if (!input || !output) {
    return false;
  }
  // base_id
  if (!rosidl_runtime_c__String__copy(
      &(input->base_id), &(output->base_id)))
  {
    return false;
  }
  // target_pose
  if (!geometry_msgs__msg__Pose__copy(
      &(input->target_pose), &(output->target_pose)))
  {
    return false;
  }
  // gripper_state
  output->gripper_state = input->gripper_state;
  return true;
}

my_robot_interfaces__msg__RobotCommand *
my_robot_interfaces__msg__RobotCommand__create(void)
{
  rcutils_allocator_t allocator = rcutils_get_default_allocator();
  my_robot_interfaces__msg__RobotCommand * msg = (my_robot_interfaces__msg__RobotCommand *)allocator.allocate(sizeof(my_robot_interfaces__msg__RobotCommand), allocator.state);
  if (!msg) {
    return NULL;
  }
  memset(msg, 0, sizeof(my_robot_interfaces__msg__RobotCommand));
  bool success = my_robot_interfaces__msg__RobotCommand__init(msg);
  if (!success) {
    allocator.deallocate(msg, allocator.state);
    return NULL;
  }
  return msg;
}

void
my_robot_interfaces__msg__RobotCommand__destroy(my_robot_interfaces__msg__RobotCommand * msg)
{
  rcutils_allocator_t allocator = rcutils_get_default_allocator();
  if (msg) {
    my_robot_interfaces__msg__RobotCommand__fini(msg);
  }
  allocator.deallocate(msg, allocator.state);
}


bool
my_robot_interfaces__msg__RobotCommand__Sequence__init(my_robot_interfaces__msg__RobotCommand__Sequence * array, size_t size)
{
  if (!array) {
    return false;
  }
  rcutils_allocator_t allocator = rcutils_get_default_allocator();
  my_robot_interfaces__msg__RobotCommand * data = NULL;

  if (size) {
    data = (my_robot_interfaces__msg__RobotCommand *)allocator.zero_allocate(size, sizeof(my_robot_interfaces__msg__RobotCommand), allocator.state);
    if (!data) {
      return false;
    }
    // initialize all array elements
    size_t i;
    for (i = 0; i < size; ++i) {
      bool success = my_robot_interfaces__msg__RobotCommand__init(&data[i]);
      if (!success) {
        break;
      }
    }
    if (i < size) {
      // if initialization failed finalize the already initialized array elements
      for (; i > 0; --i) {
        my_robot_interfaces__msg__RobotCommand__fini(&data[i - 1]);
      }
      allocator.deallocate(data, allocator.state);
      return false;
    }
  }
  array->data = data;
  array->size = size;
  array->capacity = size;
  return true;
}

void
my_robot_interfaces__msg__RobotCommand__Sequence__fini(my_robot_interfaces__msg__RobotCommand__Sequence * array)
{
  if (!array) {
    return;
  }
  rcutils_allocator_t allocator = rcutils_get_default_allocator();

  if (array->data) {
    // ensure that data and capacity values are consistent
    assert(array->capacity > 0);
    // finalize all array elements
    for (size_t i = 0; i < array->capacity; ++i) {
      my_robot_interfaces__msg__RobotCommand__fini(&array->data[i]);
    }
    allocator.deallocate(array->data, allocator.state);
    array->data = NULL;
    array->size = 0;
    array->capacity = 0;
  } else {
    // ensure that data, size, and capacity values are consistent
    assert(0 == array->size);
    assert(0 == array->capacity);
  }
}

my_robot_interfaces__msg__RobotCommand__Sequence *
my_robot_interfaces__msg__RobotCommand__Sequence__create(size_t size)
{
  rcutils_allocator_t allocator = rcutils_get_default_allocator();
  my_robot_interfaces__msg__RobotCommand__Sequence * array = (my_robot_interfaces__msg__RobotCommand__Sequence *)allocator.allocate(sizeof(my_robot_interfaces__msg__RobotCommand__Sequence), allocator.state);
  if (!array) {
    return NULL;
  }
  bool success = my_robot_interfaces__msg__RobotCommand__Sequence__init(array, size);
  if (!success) {
    allocator.deallocate(array, allocator.state);
    return NULL;
  }
  return array;
}

void
my_robot_interfaces__msg__RobotCommand__Sequence__destroy(my_robot_interfaces__msg__RobotCommand__Sequence * array)
{
  rcutils_allocator_t allocator = rcutils_get_default_allocator();
  if (array) {
    my_robot_interfaces__msg__RobotCommand__Sequence__fini(array);
  }
  allocator.deallocate(array, allocator.state);
}

bool
my_robot_interfaces__msg__RobotCommand__Sequence__are_equal(const my_robot_interfaces__msg__RobotCommand__Sequence * lhs, const my_robot_interfaces__msg__RobotCommand__Sequence * rhs)
{
  if (!lhs || !rhs) {
    return false;
  }
  if (lhs->size != rhs->size) {
    return false;
  }
  for (size_t i = 0; i < lhs->size; ++i) {
    if (!my_robot_interfaces__msg__RobotCommand__are_equal(&(lhs->data[i]), &(rhs->data[i]))) {
      return false;
    }
  }
  return true;
}

bool
my_robot_interfaces__msg__RobotCommand__Sequence__copy(
  const my_robot_interfaces__msg__RobotCommand__Sequence * input,
  my_robot_interfaces__msg__RobotCommand__Sequence * output)
{
  if (!input || !output) {
    return false;
  }
  if (output->capacity < input->size) {
    const size_t allocation_size =
      input->size * sizeof(my_robot_interfaces__msg__RobotCommand);
    rcutils_allocator_t allocator = rcutils_get_default_allocator();
    my_robot_interfaces__msg__RobotCommand * data =
      (my_robot_interfaces__msg__RobotCommand *)allocator.reallocate(
      output->data, allocation_size, allocator.state);
    if (!data) {
      return false;
    }
    // If reallocation succeeded, memory may or may not have been moved
    // to fulfill the allocation request, invalidating output->data.
    output->data = data;
    for (size_t i = output->capacity; i < input->size; ++i) {
      if (!my_robot_interfaces__msg__RobotCommand__init(&output->data[i])) {
        // If initialization of any new item fails, roll back
        // all previously initialized items. Existing items
        // in output are to be left unmodified.
        for (; i-- > output->capacity; ) {
          my_robot_interfaces__msg__RobotCommand__fini(&output->data[i]);
        }
        return false;
      }
    }
    output->capacity = input->size;
  }
  output->size = input->size;
  for (size_t i = 0; i < input->size; ++i) {
    if (!my_robot_interfaces__msg__RobotCommand__copy(
        &(input->data[i]), &(output->data[i])))
    {
      return false;
    }
  }
  return true;
}
