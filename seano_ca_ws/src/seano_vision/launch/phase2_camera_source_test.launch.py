#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generic SEANO camera source launcher.

This launch is intentionally tracked because phase7_cuav_usb_hardware.launch.py
and demo_full_ca.launch.py can select it with:
  camera_launch:=phase2_camera_source_test.launch.py

Supported inputs:
- source:=url      with url:=rtsp://... or url:=/path/to/video.mp4
- source:=device   with device_path:=/dev/video0 or device_index:=0
- source:=pipeline with pipeline:=<gstreamer pipeline string>
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.conditions import IfCondition
from launch.substitutions import EnvironmentVariable, LaunchConfiguration, PathJoinSubstitution, PythonExpression
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def _nonempty_or_default(value, default):
    return PythonExpression(["'", value, "' if '", value, "' != '' else '", default, "'"])


def generate_launch_description():
    profile = LaunchConfiguration("profile")
    source = LaunchConfiguration("source")
    backend = LaunchConfiguration("backend")
    url = LaunchConfiguration("url")
    pipeline = LaunchConfiguration("pipeline")
    device_path = LaunchConfiguration("device_path")
    device_index = LaunchConfiguration("device_index")
    device_fourcc = LaunchConfiguration("device_fourcc")
    device_width = LaunchConfiguration("device_width")
    device_height = LaunchConfiguration("device_height")
    device_fps = LaunchConfiguration("device_fps")
    topic_best_effort = LaunchConfiguration("topic_best_effort")
    topic_reliable = LaunchConfiguration("topic_reliable")
    frame_id = LaunchConfiguration("frame_id")
    max_fps = LaunchConfiguration("max_fps")
    max_age_ms = LaunchConfiguration("max_age_ms")
    reconnect_sec = LaunchConfiguration("reconnect_sec")
    log_stats_sec = LaunchConfiguration("log_stats_sec")
    publish_best_effort = LaunchConfiguration("publish_best_effort")
    publish_reliable = LaunchConfiguration("publish_reliable")
    output_encoding = LaunchConfiguration("output_encoding")
    swap_rb = LaunchConfiguration("swap_rb")
    rotate = LaunchConfiguration("rotate")
    resize_width = LaunchConfiguration("resize_width")
    resize_height = LaunchConfiguration("resize_height")
    record = LaunchConfiguration("record")
    bag_base_dir = LaunchConfiguration("bag_base_dir")
    bag_prefix = LaunchConfiguration("bag_prefix")
    duration_s = LaunchConfiguration("duration_s")

    camera = Node(
        package="seano_vision",
        executable="camera_node",
        name="camera_hp",
        output="screen",
        emulate_tty=True,
        parameters=[
            {
                "profile": profile,
                "source": _nonempty_or_default(source, "url"),
                "backend": _nonempty_or_default(backend, "opencv"),
                "url": url,
                "pipeline": pipeline,
                "device_path": device_path,
                "device_index": ParameterValue(_nonempty_or_default(device_index, "0"), value_type=int),
                "device_fourcc": device_fourcc,
                "device_width": ParameterValue(_nonempty_or_default(device_width, "640"), value_type=int),
                "device_height": ParameterValue(_nonempty_or_default(device_height, "480"), value_type=int),
                "device_fps": ParameterValue(_nonempty_or_default(device_fps, "30"), value_type=float),
                "max_fps": ParameterValue(_nonempty_or_default(max_fps, "15.0"), value_type=float),
                "max_age_ms": ParameterValue(_nonempty_or_default(max_age_ms, "120"), value_type=float),
                "reconnect_sec": ParameterValue(_nonempty_or_default(reconnect_sec, "0.5"), value_type=float),
                "log_stats_sec": ParameterValue(_nonempty_or_default(log_stats_sec, "2.0"), value_type=float),
                "topic_best_effort": topic_best_effort,
                "topic_reliable": topic_reliable,
                "frame_id": _nonempty_or_default(frame_id, "camera"),
                "publish_best_effort": ParameterValue(publish_best_effort, value_type=bool),
                "publish_reliable": ParameterValue(publish_reliable, value_type=bool),
                "output_encoding": output_encoding,
                "swap_rb": ParameterValue(swap_rb, value_type=bool),
                "rotate": ParameterValue(rotate, value_type=int),
                "resize_width": ParameterValue(resize_width, value_type=int),
                "resize_height": ParameterValue(resize_height, value_type=int),
                "publish_in_reader": False,
            }
        ],
    )

    bag_dir = PythonExpression([
        "'", bag_base_dir, "' if '", bag_base_dir, "' != '' else '",
        EnvironmentVariable("HOME", default_value="/tmp"), "/bags'"
    ])
    bag_path = PathJoinSubstitution([bag_dir, bag_prefix])
    duration_arg = PythonExpression([
        "'--duration=", duration_s, "' if float('", duration_s, "') > 0.0 else ''"
    ])

    recorder = ExecuteProcess(
        cmd=[
            "ros2", "bag", "record", "-o", bag_path,
            topic_best_effort, topic_reliable,
            duration_arg,
        ],
        output="screen",
        condition=IfCondition(record),
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("profile", default_value=""),
            DeclareLaunchArgument("source", default_value=EnvironmentVariable("SEANO_CA_CAMERA_SOURCE", default_value="url")),
            DeclareLaunchArgument("backend", default_value=EnvironmentVariable("SEANO_CA_CAMERA_BACKEND", default_value="opencv")),
            DeclareLaunchArgument("url", default_value=EnvironmentVariable("SEANO_CA_CAMERA_URL", default_value="")),
            DeclareLaunchArgument("pipeline", default_value=EnvironmentVariable("SEANO_CA_CAMERA_PIPELINE", default_value="")),
            DeclareLaunchArgument("device_path", default_value=EnvironmentVariable("SEANO_CA_CAMERA_DEVICE_PATH", default_value="")),
            DeclareLaunchArgument("device_index", default_value=EnvironmentVariable("SEANO_CA_CAMERA_DEVICE_INDEX", default_value="0")),
            DeclareLaunchArgument("device_fourcc", default_value=EnvironmentVariable("SEANO_CA_CAMERA_DEVICE_FOURCC", default_value="MJPG")),
            DeclareLaunchArgument("device_width", default_value=EnvironmentVariable("SEANO_CA_CAMERA_DEVICE_WIDTH", default_value="640")),
            DeclareLaunchArgument("device_height", default_value=EnvironmentVariable("SEANO_CA_CAMERA_DEVICE_HEIGHT", default_value="480")),
            DeclareLaunchArgument("device_fps", default_value=EnvironmentVariable("SEANO_CA_CAMERA_DEVICE_FPS", default_value="30")),
            DeclareLaunchArgument("topic_best_effort", default_value=EnvironmentVariable("SEANO_CA_CAMERA_TOPIC_BEST_EFFORT", default_value="/seano/camera/image_raw")),
            DeclareLaunchArgument("topic_reliable", default_value=EnvironmentVariable("SEANO_CA_CAMERA_TOPIC_RELIABLE", default_value="/seano/camera/image_raw_reliable")),
            DeclareLaunchArgument("frame_id", default_value=EnvironmentVariable("SEANO_CA_CAMERA_FRAME_ID", default_value="camera")),
            DeclareLaunchArgument("max_fps", default_value=EnvironmentVariable("SEANO_CA_CAMERA_MAX_FPS", default_value="15.0")),
            DeclareLaunchArgument("max_age_ms", default_value=EnvironmentVariable("SEANO_CA_CAMERA_MAX_AGE_MS", default_value="120")),
            DeclareLaunchArgument("reconnect_sec", default_value="0.5"),
            DeclareLaunchArgument("log_stats_sec", default_value="2.0"),
            DeclareLaunchArgument("publish_best_effort", default_value="true"),
            DeclareLaunchArgument("publish_reliable", default_value="true"),
            DeclareLaunchArgument("output_encoding", default_value="bgr8"),
            DeclareLaunchArgument("swap_rb", default_value="false"),
            DeclareLaunchArgument("rotate", default_value="0"),
            DeclareLaunchArgument("resize_width", default_value="0"),
            DeclareLaunchArgument("resize_height", default_value="0"),
            DeclareLaunchArgument("record", default_value=EnvironmentVariable("SEANO_CA_CAMERA_RECORD", default_value="false")),
            DeclareLaunchArgument("bag_base_dir", default_value=EnvironmentVariable("SEANO_CA_CAMERA_BAG_BASE_DIR", default_value="")),
            DeclareLaunchArgument("bag_prefix", default_value=EnvironmentVariable("SEANO_CA_CAMERA_BAG_PREFIX", default_value="phase2_camera")),
            DeclareLaunchArgument("duration_s", default_value=EnvironmentVariable("SEANO_CA_CAMERA_DURATION_S", default_value="0")),
            camera,
            recorder,
        ]
    )
