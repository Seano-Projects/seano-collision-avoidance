"""Dedicated AUTO takeover profile; reuses external MAVROS and RC publisher."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    package = FindPackageShare("seano_vision")
    session_id = LaunchConfiguration("session_id")
    log_dir = LaunchConfiguration("log_dir")
    event_log_root = LaunchConfiguration("event_log_root")
    event_run_id = LaunchConfiguration("event_run_id")
    mapping_profile = LaunchConfiguration("mapping_profile")
    steering_channel_index = LaunchConfiguration("steering_channel_index")
    throttle_channel_index = LaunchConfiguration("throttle_channel_index")
    pwm_min = LaunchConfiguration("pwm_min")
    neutral_throttle_pwm = LaunchConfiguration("neutral_throttle_pwm")
    pwm_max = LaunchConfiguration("pwm_max")
    cruise_reference_throttle_percent = LaunchConfiguration(
        "cruise_reference_throttle_percent"
    )
    slow_factor = LaunchConfiguration("slow_factor")
    slow_throttle_percent = LaunchConfiguration("slow_throttle_percent")
    minimum_effective_throttle_percent = LaunchConfiguration(
        "minimum_effective_throttle_percent"
    )
    maximum_test_throttle_percent = LaunchConfiguration(
        "maximum_test_throttle_percent"
    )
    maximum_steering_percent = LaunchConfiguration("maximum_steering_percent")
    maximum_motion_duration_s = LaunchConfiguration("maximum_motion_duration_s")
    command_freshness_watchdog_s = LaunchConfiguration(
        "command_freshness_watchdog_s"
    )
    motion_delivery_timeout_s = LaunchConfiguration(
        "motion_delivery_timeout_s"
    )
    release_timeout_s = LaunchConfiguration("release_timeout_s")
    final_release_timeout_s = LaunchConfiguration(
        "final_release_timeout_s"
    )
    turn_throttle_percent = LaunchConfiguration("turn_throttle_percent")
    maximum_takeover_duration_s = LaunchConfiguration(
        "maximum_takeover_duration_s"
    )
    startup_grace_s = LaunchConfiguration("startup_grace_s")
    hazard_debounce_s = LaunchConfiguration("hazard_debounce_s")
    clear_hold_s = LaunchConfiguration("clear_hold_s")
    mode_timeout_s = LaunchConfiguration("mode_timeout_s")
    mode_retry_interval_s = LaunchConfiguration("mode_retry_interval_s")
    auto_rejoin_verify_s = LaunchConfiguration("auto_rejoin_verify_s")
    web_video_available = LaunchConfiguration("web_video_available")

    pipeline = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([package, "launch", "phase7_cuav_usb_hardware.launch.py"])
        ),
        launch_arguments={
            "use_mavros": "false",
            "use_rc_override_bridge": "false",
            "use_mode_manager": "false",
            "use_takeover_manager": "true",
            "use_thruster_test_guardian": "false",
            "use_thruster_test_hud": "false",
            "use_guarded_thruster_test_adapter": "true",
            "use_thruster_adapter_preview": "true",
            "publish_thruster_preview_actuator_path_ready": "false",
            "thruster_preview_dry_run": "false",
            "hardware_output_enabled": "true",
            "external_interface_confirmed": "true",
            "external_arbitration_confirmed": "true",
            "hardware_test_enabled": "true",
            "mqtt_publish_enabled": "true",
            "hardware_test_operator_confirmed": "true",
            "shared_mqtt_test_confirmed": "true",
            "tether_confirmed": "true",
            "emergency_stop_confirmed": "true",
            "exclusive_test_window_confirmed": "true",
            "hardware_test_session_id": session_id,
            "hardware_test_log_dir": log_dir,
            "hardware_test_required_fcu_mode": "MANUAL",
            "hardware_test_maximum_throttle_percent": maximum_test_throttle_percent,
            "hardware_test_maximum_allowed_throttle_percent": "58.0",
            "hardware_test_mapping_profile": mapping_profile,
            "hardware_test_cruise_reference_throttle_percent": (
                cruise_reference_throttle_percent
            ),
            "hardware_test_slow_factor": slow_factor,
            "hardware_test_slow_throttle_percent": slow_throttle_percent,
            "hardware_test_minimum_effective_throttle_percent": (
                minimum_effective_throttle_percent
            ),
            "hardware_test_turn_throttle_percent": turn_throttle_percent,
            "hardware_test_neutral_throttle_pwm": neutral_throttle_pwm,
            "hardware_test_maximum_steering_percent": maximum_steering_percent,
            "hardware_test_maximum_allowed_steering_percent": "100.0",
            "hardware_test_steering_channel_index": steering_channel_index,
            "hardware_test_throttle_channel_index": throttle_channel_index,
            "hardware_test_pwm_min": pwm_min,
            "hardware_test_pwm_max": pwm_max,
            "hardware_test_maximum_motion_duration_s": maximum_motion_duration_s,
            "hardware_test_command_topic": "/ca/auto_takeover/hardware_command",
            "hardware_test_bounded_stop_neutral": "true",
            "hardware_test_neutral_repetitions": "1",
            "hardware_test_release_repetitions": "1",
            "hardware_test_hold_stop_on_failsafe": "true",
            "hardware_test_release_without_extra_neutral": "true",
            "hardware_test_recoverable_permission_loss": "true",
            "master_enable_on_start": "true",
            "pool_turn_away_policy": "true",
            "require_actuator_path_ready": "true",
            "record": "false",
            "use_event_logger": "true",
            "event_log_root": event_log_root,
            "event_run_id": event_run_id,
            "ca_det_model_path": "yolov8n.engine",
            "ca_det_imgsz": "416",
            "ca_det_half": "true",
            "ca_det_publish_annotated": "false",
        }.items(),
    )
    manager = Node(
        package="seano_vision",
        executable="auto_takeover_manager_node",
        name="auto_takeover_manager_node",
        output="screen",
        parameters=[{
            "enabled": True,
            "operator_confirmed": True,
            "mode_takeover_confirmed": True,
            "session_id": session_id,
            "log_dir": log_dir,
            "startup_grace_s": ParameterValue(startup_grace_s, value_type=float),
            "hazard_debounce_s": ParameterValue(hazard_debounce_s, value_type=float),
            "clear_hold_s": ParameterValue(clear_hold_s, value_type=float),
            "mode_timeout_s": ParameterValue(mode_timeout_s, value_type=float),
            "maximum_motion_duration_s": ParameterValue(
                maximum_motion_duration_s, value_type=float
            ),
            "maximum_takeover_duration_s": ParameterValue(
                maximum_takeover_duration_s, value_type=float
            ),
            "command_freshness_watchdog_s": ParameterValue(
                command_freshness_watchdog_s, value_type=float
            ),
            "motion_delivery_timeout_s": ParameterValue(
                motion_delivery_timeout_s, value_type=float
            ),
            "release_timeout_s": ParameterValue(
                release_timeout_s, value_type=float
            ),
            "final_release_timeout_s": ParameterValue(
                final_release_timeout_s, value_type=float
            ),
            "maximum_mode_requests": 3,
            "mode_retry_interval_s": ParameterValue(
                mode_retry_interval_s, value_type=float
            ),
            "auto_rejoin_verify_s": ParameterValue(
                auto_rejoin_verify_s, value_type=float
            ),
            "mapping_profile": mapping_profile,
            "steering_channel_index": ParameterValue(
                steering_channel_index, value_type=int
            ),
            "throttle_channel_index": ParameterValue(
                throttle_channel_index, value_type=int
            ),
            "pwm_min": ParameterValue(pwm_min, value_type=int),
            "neutral_throttle_pwm": ParameterValue(
                neutral_throttle_pwm, value_type=int
            ),
            "pwm_max": ParameterValue(pwm_max, value_type=int),
            "slow_throttle_percent": ParameterValue(
                slow_throttle_percent, value_type=float
            ),
            "cruise_reference_throttle_percent": ParameterValue(
                cruise_reference_throttle_percent, value_type=float
            ),
            "slow_factor": ParameterValue(slow_factor, value_type=float),
            "minimum_effective_throttle_percent": ParameterValue(
                minimum_effective_throttle_percent, value_type=float
            ),
            "maximum_test_throttle_percent": ParameterValue(
                maximum_test_throttle_percent, value_type=float
            ),
            "turn_throttle_percent": ParameterValue(
                turn_throttle_percent, value_type=float
            ),
            "maximum_steering_percent": ParameterValue(
                maximum_steering_percent, value_type=float
            ),
            "web_video_available": ParameterValue(
                web_video_available, value_type=bool
            ),
        }],
    )
    hud = Node(
        package="seano_vision",
        executable="auto_takeover_hud_node",
        name="auto_takeover_hud_node",
        output="screen",
    )
    return LaunchDescription([
        DeclareLaunchArgument("session_id", default_value=""),
        DeclareLaunchArgument("log_dir", default_value=""),
        DeclareLaunchArgument("event_log_root", default_value=""),
        DeclareLaunchArgument("event_run_id", default_value=""),
        DeclareLaunchArgument(
            "mapping_profile", default_value="SEAPORTAL_ACTUAL"
        ),
        DeclareLaunchArgument("steering_channel_index", default_value="0"),
        DeclareLaunchArgument("throttle_channel_index", default_value="2"),
        DeclareLaunchArgument("pwm_min", default_value="1000"),
        DeclareLaunchArgument("neutral_throttle_pwm", default_value="1500"),
        DeclareLaunchArgument("pwm_max", default_value="2000"),
        DeclareLaunchArgument(
            "cruise_reference_throttle_percent", default_value="100.0"
        ),
        DeclareLaunchArgument("slow_factor", default_value="0.58"),
        DeclareLaunchArgument("slow_throttle_percent", default_value="58.0"),
        DeclareLaunchArgument(
            "minimum_effective_throttle_percent", default_value="58.0"
        ),
        DeclareLaunchArgument(
            "maximum_test_throttle_percent", default_value="58.0"
        ),
        DeclareLaunchArgument("turn_throttle_percent", default_value="0.0"),
        DeclareLaunchArgument("maximum_steering_percent", default_value="100.0"),
        DeclareLaunchArgument("maximum_motion_duration_s", default_value="2.0"),
        DeclareLaunchArgument(
            "command_freshness_watchdog_s", default_value="2.0"
        ),
        DeclareLaunchArgument(
            "motion_delivery_timeout_s", default_value="0.75"
        ),
        DeclareLaunchArgument("release_timeout_s", default_value="1.0"),
        DeclareLaunchArgument(
            "final_release_timeout_s", default_value="0.5"
        ),
        DeclareLaunchArgument("maximum_takeover_duration_s", default_value="15.0"),
        DeclareLaunchArgument("startup_grace_s", default_value="8.0"),
        DeclareLaunchArgument("hazard_debounce_s", default_value="0.4"),
        DeclareLaunchArgument("clear_hold_s", default_value="2.5"),
        DeclareLaunchArgument("mode_timeout_s", default_value="3.0"),
        DeclareLaunchArgument(
            "mode_retry_interval_s", default_value="1.0"
        ),
        DeclareLaunchArgument(
            "auto_rejoin_verify_s", default_value="0.5"
        ),
        DeclareLaunchArgument("web_video_available", default_value="false"),
        pipeline,
        manager,
        hud,
    ])
