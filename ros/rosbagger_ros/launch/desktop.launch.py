"""Launch the rosbagger desktop GUI inside a sourced ROS 2 environment.

Usage:
    ros2 launch rosbagger_ros desktop.launch.py
    ros2 launch rosbagger_ros desktop.launch.py bag:=/path/to/bag

Runs the ``rosbagger-desktop`` console script (installed via pip; see this
package's README), so the GUI inherits the sourced ROS environment — its live
record / replay / RViz / Rerun features operate on the same ROS graph as the rest
of your launch. Closing the GUI window shuts the launch down.
"""

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    ExecuteProcess,
    OpaqueFunction,
    RegisterEventHandler,
)
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.substitutions import LaunchConfiguration


def _launch_setup(context, *args, **kwargs):
    bag = LaunchConfiguration("bag").perform(context).strip()
    cmd = ["rosbagger-desktop"]
    if bag:
        cmd.append(bag)
    gui = ExecuteProcess(cmd=cmd, output="screen")
    # Closing the GUI window ends `ros2 launch` cleanly.
    shutdown_on_close = RegisterEventHandler(
        OnProcessExit(target_action=gui, on_exit=[EmitEvent(event=Shutdown())])
    )
    return [gui, shutdown_on_close]


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "bag",
                default_value="",
                description="Optional path to a bag (file or directory) to open. "
                "Empty opens the GUI with no bag loaded.",
            ),
            OpaqueFunction(function=_launch_setup),
        ]
    )
