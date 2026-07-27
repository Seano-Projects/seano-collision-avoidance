import json
import os
from pathlib import Path
import subprocess
import unittest

from seano_vision.thruster_preview import command_to_left_right
from seano_vision.thruster_test_safety import (
    AdapterCore,
    FakeTransport,
    GuardianCore,
    GuardianInputs,
    OWN_MQTT_ECHO,
    OwnMessageRegistry,
    StaticGates,
    TestLimits as Limits,
    classify_mqtt_message,
    command_to_test_output,
    publish_action_tracked,
    publish_actions,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
BASELINE = REPO_ROOT / "seano_ca_ws" / "run_pool_existing_control_path.sh"
HARDWARE_SCRIPT = REPO_ROOT / "seano_ca_ws" / "run_pool_thruster_hardware_test.sh"
LAUNCH = PACKAGE_ROOT / "launch" / "phase7_cuav_usb_hardware.launch.py"
ADAPTER_NODE = PACKAGE_ROOT / "seano_vision" / "guarded_thruster_test_adapter_node.py"
GUARDIAN_NODE = PACKAGE_ROOT / "seano_vision" / "thruster_test_safety_guardian_node.py"
HUD_NODE = PACKAGE_ROOT / "seano_vision" / "thruster_test_hud_node.py"


def gates(**overrides):
    values = dict(
        hardware_test_enabled=True,
        mqtt_publish_enabled=True,
        operator_confirmed=True,
        shared_mqtt_test_confirmed=True,
        tether_confirmed=True,
        emergency_stop_confirmed=True,
        exclusive_test_window_confirmed=True,
        foreign_command_monitor_enabled=True,
    )
    values.update(overrides)
    return StaticGates(**values)


def inputs(**overrides):
    values = dict(
        now=10.0, started_at=0.0, adapter_heartbeat_at=10.0,
        command_at=10.0, safe_command_at=10.0, command="HOLD_COURSE",
        failsafe=False, lost_perception=False, mqtt_connected=True,
        foreign_command=False, operator_enable=True, throttle_percent=0.0,
        steering_percent=0.0, fcu_connected=True, fcu_armed=True,
        fcu_mode="MANUAL", required_fcu_mode="MANUAL", rc_publisher_count=1,
        rc_publisher_name="/usv/thruster", rc_subscriber_present=True,
    )
    values.update(overrides)
    return GuardianInputs(**values)


def guardian(custom_gates=None, custom_limits=None):
    return GuardianCore(
        custom_gates or gates(), custom_limits or Limits(),
        observation_window_s=0.0, startup_grace_s=0.0,
    )


def guardian_waiting_for_arm():
    core = guardian()
    decision = core.evaluate(inputs(fcu_armed=False))
    assert decision.status == "WAITING_FOR_OPERATOR_ARM"
    return core


def guardian_ready():
    core = guardian_waiting_for_arm()
    decision = core.evaluate(inputs())
    assert decision.status == "READY_FOR_OBSTACLE_TEST"
    return core


class ThrusterHardwareSafetyTests(unittest.TestCase):
    def test_01_baseline_does_not_enable_adapter(self):
        self.assertIn("use_guarded_thruster_test_adapter:=false", BASELINE.read_text())

    def test_02_baseline_does_not_enable_guardian(self):
        self.assertIn("use_thruster_test_guardian:=false", BASELINE.read_text())

    def test_03_baseline_remains_dry_run(self):
        text = BASELINE.read_text()
        self.assertIn("thruster_preview_dry_run:=true", text)
        self.assertIn("hardware_output_enabled:=false", text)

    def test_04_hardware_script_requires_first_flag(self):
        result = subprocess.run([str(HARDWARE_SCRIPT)], text=True, input="", capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CA_HARDWARE_TEST_ENABLE", result.stdout)

    def test_05_hardware_script_requires_second_flag(self):
        env = dict(os.environ, CA_HARDWARE_TEST_ENABLE="yes")
        result = subprocess.run([str(HARDWARE_SCRIPT)], env=env, text=True, input="", capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CA_SHARED_MQTT_TEST_CONFIRM", result.stdout)

    def test_06_hardware_script_requires_exact_confirmation(self):
        env = dict(os.environ, CA_HARDWARE_TEST_ENABLE="yes", CA_SHARED_MQTT_TEST_CONFIRM="yes",
                   CA_TETHER_CONFIRMED="yes", CA_EMERGENCY_STOP_CONFIRMED="yes",
                   CA_EXCLUSIVE_TEST_WINDOW_CONFIRMED="yes")
        result = subprocess.run([str(HARDWARE_SCRIPT)], env=env, text=True,
                                input="ENABLE GUARDED THRUSTER TEST\n", capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not match exactly", result.stdout)

    def test_07_dry_check_never_starts_ros_or_mqtt(self):
        result = subprocess.run([str(HARDWARE_SCRIPT), "--dry-check"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("No MQTT connection opened", result.stdout)

    def test_08_one_static_gate_false_blocks_motion(self):
        decision = guardian(gates(tether_confirmed=False)).evaluate(inputs())
        self.assertFalse(decision.motion_allowed)

    def test_09_all_gates_true_allow_safe_state(self):
        decision = guardian_waiting_for_arm().evaluate(inputs())
        self.assertFalse(decision.motion_allowed)
        self.assertEqual(decision.status, "READY_FOR_OBSTACLE_TEST")
        self.assertTrue(decision.actuator_path_ready)

    def test_10_defaults_do_not_publish(self):
        self.assertTrue(StaticGates().closed_reasons())
        self.assertFalse(StaticGates().mqtt_publish_enabled)

    def test_11_first_test_limits(self):
        valid, _ = Limits().validate_first_test()
        self.assertTrue(valid)
        self.assertEqual(Limits().maximum_throttle_percent, 10.0)
        self.assertEqual(Limits().maximum_steering_percent, 15.0)

    def test_12_limit_increase_rejected(self):
        self.assertFalse(Limits(maximum_throttle_percent=10.1).validate_first_test()[0])
        self.assertFalse(Limits(maximum_steering_percent=15.1).validate_first_test()[0])

    def test_13_reverse_is_blocked(self):
        self.assertEqual(command_to_test_output("SLOW_DOWN", -0.2, -0.2, Limits())[2], "REVERSE_DETECTED")

    def test_14_slow_down_clamps_to_ten(self):
        left, right = command_to_left_right("SLOW_DOWN")[:2]
        self.assertEqual(command_to_test_output("SLOW_DOWN", left, right, Limits())[:2], (10.0, 0.0))

    def test_15_turn_left_clamps(self):
        left, right = command_to_left_right("TURN_LEFT_SLOW")[:2]
        self.assertEqual(command_to_test_output("TURN_LEFT_SLOW", left, right, Limits())[:2], (10.0, -15.0))

    def test_16_turn_right_clamps(self):
        left, right = command_to_left_right("TURN_RIGHT_SLOW")[:2]
        self.assertEqual(command_to_test_output("TURN_RIGHT_SLOW", left, right, Limits())[:2], (10.0, 15.0))

    def test_17_full_turns_use_same_limits(self):
        for command, steering in (("TURN_LEFT", -15.0), ("TURN_RIGHT", 15.0)):
            left, right = command_to_left_right(command)[:2]
            self.assertEqual(command_to_test_output(command, left, right, Limits())[:2], (10.0, steering))

    def test_18_stop_is_neutral(self):
        core = AdapterCore(session_id="s")
        actions = core.update("STOP", 0.5, 0.5, True, now=1.0)
        self.assertEqual(actions[0].kind, "NEUTRAL")
        self.assertEqual((actions[0].payload["throttle"], actions[0].payload["steering"]), (0.0, 0.0))

    def test_19_hold_neutral_then_release_after_control(self):
        core = AdapterCore(session_id="s")
        core.update("SLOW_DOWN", 0.165, 0.165, True, now=1.0)
        self.assertEqual([a.kind for a in core.update("HOLD_COURSE", 0, 0, True, now=2.0)], ["NEUTRAL", "RELEASE"])

    def test_20_foreign_before_motion_blocks_start(self):
        core = AdapterCore(session_id="s")
        actions = core.handle_incoming('{"source":"other"}')
        self.assertTrue(core.aborted)
        self.assertEqual(core.abort_reason, "FOREIGN_UNKNOWN_SCHEMA")
        self.assertEqual([a.kind for a in actions], ["RELEASE"])

    def test_21_foreign_during_motion_has_no_neutral_barrage(self):
        core = AdapterCore(session_id="s")
        core.update("SLOW_DOWN", 0.165, 0.165, True, now=1.0)
        actions = core.handle_incoming('{"source":"other"}')
        self.assertEqual([a.kind for a in actions], ["RELEASE"])

    def test_22_own_echo_is_not_foreign(self):
        core = AdapterCore(session_id="s")
        action = core.update("STOP", 0, 0, True, now=1.0)[0]
        registry = OwnMessageRegistry()
        transport = FakeTransport()
        publish_action_tracked(transport, registry, action)
        raw = transport.published[0][1]
        message = classify_mqtt_message(raw, own_registry=registry)
        self.assertEqual(message.classification, OWN_MQTT_ECHO)
        self.assertEqual(core.handle_classified(message), [])

    def test_23_other_session_is_foreign(self):
        core = AdapterCore(session_id="s")
        raw = '{"source":"collision_avoidance_test","session_id":"other","sequence":1}'
        self.assertEqual(core.handle_incoming(raw)[0].kind, "RELEASE")

    def test_24_adapter_heartbeat_timeout_aborts(self):
        core = guardian_ready()
        decision = core.evaluate(inputs(now=11.0, adapter_heartbeat_at=8.0))
        self.assertEqual(decision.abort_reason, "ADAPTER_HEARTBEAT_STALE")

    def test_25_command_timeout_aborts(self):
        core = guardian_ready()
        self.assertEqual(core.evaluate(inputs(
            now=11.0, adapter_heartbeat_at=11.0, command_at=8.0,
            safe_command_at=11.0,
        )).abort_reason, "COMMAND_STALE")

    def test_26_safe_command_timeout_aborts(self):
        core = guardian_ready()
        self.assertEqual(core.evaluate(inputs(
            now=11.0, adapter_heartbeat_at=11.0, command_at=11.0,
            safe_command_at=8.0,
        )).abort_reason, "SAFE_COMMAND_STALE")

    def test_27_failsafe_aborts(self):
        core = guardian_ready()
        self.assertEqual(core.evaluate(inputs(failsafe=True)).abort_reason, "FAILSAFE_ACTIVE")

    def test_28_lost_perception_aborts(self):
        core = guardian_ready()
        self.assertEqual(core.evaluate(inputs(lost_perception=True)).abort_reason, "LOST_PERCEPTION")

    def test_29_mqtt_disconnect_aborts(self):
        core = guardian_ready()
        self.assertEqual(core.evaluate(inputs(mqtt_connected=False)).abort_reason, "MQTT_DISCONNECTED")

    def test_30_maximum_duration_aborts(self):
        core = guardian_waiting_for_arm()
        self.assertTrue(core.evaluate(inputs(command="SLOW_DOWN", throttle_percent=10.0)).motion_allowed)
        later = inputs(now=12.1, adapter_heartbeat_at=12.1, command_at=12.1,
                       safe_command_at=12.1, command="SLOW_DOWN", throttle_percent=10.0)
        self.assertEqual(core.evaluate(later).abort_reason, "MAXIMUM_MOTION_DURATION_EXCEEDED")

    def test_31_shutdown_is_bounded_neutral_then_release(self):
        core = AdapterCore(session_id="s")
        core.update("SLOW_DOWN", 0.1, 0.1, True, now=0.5)
        actions = core.shutdown(now=1.0)
        self.assertEqual([a.kind for a in actions], ["NEUTRAL"] * 3 + ["RELEASE"] * 3)

    def test_31a_shutdown_before_motion_publishes_nothing(self):
        self.assertEqual(AdapterCore(session_id="s").shutdown(now=1.0), [])

    def test_31b_internal_abort_is_bounded_neutral_then_release(self):
        actions = AdapterCore(session_id="s").abort("HEARTBEAT_STALE")
        self.assertEqual([a.kind for a in actions], ["NEUTRAL"] * 3 + ["RELEASE"] * 3)

    def test_32_retain_is_always_false(self):
        core = AdapterCore(session_id="s")
        actions = core.update("STOP", 0, 0, True, now=1.0)
        transport = FakeTransport()
        publish_actions(transport, actions)
        self.assertTrue(all(retain is False for _, _, _, retain in transport.published))

    def test_33_no_rc_override_publisher_in_new_nodes(self):
        for path in (ADAPTER_NODE, GUARDIAN_NODE):
            self.assertNotIn('create_publisher(OverrideRCIn', path.read_text())

    def test_34_hardware_runtime_disables_mode_manager_and_bridge(self):
        text = HARDWARE_SCRIPT.read_text()
        self.assertIn("use_mode_manager:=false", text)
        self.assertIn("use_mavros:=false", text)
        self.assertIn("use_rc_override_bridge:=false", text)
        self.assertNotIn("ros2 service call", text)

    def test_35_launch_hardware_defaults_are_false(self):
        text = LAUNCH.read_text()
        for name in ("use_guarded_thruster_test_adapter", "use_thruster_test_guardian",
                     "hardware_test_enabled", "mqtt_publish_enabled", "shared_mqtt_test_confirmed",
                     "tether_confirmed", "emergency_stop_confirmed", "exclusive_test_window_confirmed"):
            self.assertIn(f'DeclareLaunchArgument("{name}", default_value="false")', text)

    def test_36_guardian_is_ordered_before_delayed_adapter(self):
        text = LAUNCH.read_text()
        self.assertLess(text.index("hardware_guardian = Node("), text.index("hardware_adapter = TimerAction"))

    def test_37_baseline_and_hardware_cannot_enable_together_by_script(self):
        baseline = BASELINE.read_text()
        hardware = HARDWARE_SCRIPT.read_text()
        self.assertIn("hardware_test_enabled:=false", baseline)
        self.assertIn("hardware_test_enabled:=true", hardware)
        self.assertIn("guarded_thruster_test_adapter_node|thruster_test_safety_guardian_node", baseline)
        self.assertIn("A collision-avoidance pipeline is already active", hardware)

    def test_38_external_source_paths_are_absent(self):
        text = "\n".join((HARDWARE_SCRIPT.read_text(), ADAPTER_NODE.read_text(), GUARDIAN_NODE.read_text()))
        self.assertNotIn("/home/seano/Seano_ws", text)
        self.assertNotIn("systemctl", text)

    def test_39_credential_check_reports_presence_without_values(self):
        env = dict(
            os.environ,
            SEANO_MQTT_HOST="host-value-must-not-appear",
            SEANO_MQTT_PORT="8883",
            SEANO_MQTT_USERNAME="username-value-must-not-appear",
            SEANO_MQTT_PASSWORD="password-value-must-not-appear",
            SEANO_MQTT_CA_CERT="certificate-path-must-not-appear",
        )
        result = subprocess.run(
            [str(HARDWARE_SCRIPT), "--credential-check"], env=env,
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(result.stdout.splitlines()), 8)
        self.assertIn("MQTT host: configured", result.stdout)
        self.assertIn("MQTT username: configured", result.stdout)
        self.assertIn("MQTT password: configured", result.stdout)
        self.assertIn("TLS: enabled", result.stdout)
        self.assertIn("Ready: true", result.stdout)
        for secret in (
            env["SEANO_MQTT_HOST"], env["SEANO_MQTT_USERNAME"],
            env["SEANO_MQTT_PASSWORD"], env["SEANO_MQTT_CA_CERT"],
        ):
            self.assertNotIn(secret, result.stdout)

    def test_40_credential_check_has_no_ros_mqtt_or_log_side_effects(self):
        env = {
            key: value for key, value in os.environ.items()
            if not key.startswith("SEANO_MQTT_")
        }
        result = subprocess.run(
            [str(HARDWARE_SCRIPT), "--credential-check"], env=env,
            text=True, capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(result.stdout.splitlines()), 8)
        self.assertIn("Ready: false", result.stdout)
        self.assertNotIn("GUARDED SHARED-MQTT", result.stdout)

    def test_41_disarmed_startup_waits_for_operator_without_abort(self):
        decision = guardian().evaluate(inputs(fcu_armed=False))
        self.assertEqual(decision.status, "WAITING_FOR_OPERATOR_ARM")
        self.assertEqual(decision.abort_reason, "")
        self.assertFalse(decision.motion_allowed)

    def test_42_stale_commands_during_startup_grace_do_not_abort(self):
        core = GuardianCore(gates(), Limits(), observation_window_s=1.0, startup_grace_s=8.0)
        decision = core.evaluate(inputs(
            now=2.0, started_at=0.0, command_at=0.0, safe_command_at=0.0,
        ))
        self.assertEqual(decision.status, "STARTING")
        self.assertEqual(decision.blocked_reason, "STARTUP_GRACE")
        self.assertFalse(core.aborted)

    def test_43_missing_heartbeat_during_startup_grace_does_not_abort(self):
        core = GuardianCore(gates(), Limits(), observation_window_s=1.0, startup_grace_s=8.0)
        decision = core.evaluate(inputs(
            now=2.0, started_at=0.0, adapter_heartbeat_at=0.0,
        ))
        self.assertEqual(decision.status, "STARTING")
        self.assertFalse(core.aborted)

    def test_44_missing_component_after_grace_is_preview_only(self):
        core = GuardianCore(gates(), Limits(), observation_window_s=1.0, startup_grace_s=8.0)
        decision = core.evaluate(inputs(
            now=9.0, started_at=0.0, adapter_heartbeat_at=0.0,
            fcu_armed=False,
        ))
        self.assertEqual(decision.status, "WAITING_FOR_CA_READY")
        self.assertEqual(decision.blocked_reason, "ADAPTER_HEARTBEAT_STALE")
        self.assertFalse(decision.motion_allowed)
        self.assertFalse(core.aborted)

    def test_45_manual_arm_after_fresh_data_reaches_armed_for_test(self):
        core = guardian()
        waiting = core.evaluate(inputs(fcu_armed=False))
        ready = core.evaluate(inputs(now=10.1, adapter_heartbeat_at=10.1,
                                     command_at=10.1, safe_command_at=10.1))
        self.assertEqual(waiting.status, "WAITING_FOR_OPERATOR_ARM")
        self.assertEqual(ready.status, "READY_FOR_OBSTACLE_TEST")
        self.assertFalse(ready.motion_allowed)
        self.assertTrue(ready.actuator_path_ready)

    def test_46_arm_alone_never_enables_motion(self):
        decision = guardian_waiting_for_arm().evaluate(inputs(command="HOLD_COURSE"))
        self.assertFalse(decision.motion_allowed)

    def test_47_valid_hazard_command_is_required_for_motion(self):
        decision = guardian_waiting_for_arm().evaluate(inputs(
            command="SLOW_DOWN", throttle_percent=10.0,
        ))
        self.assertEqual(decision.status, "MOTION_ACTIVE")
        self.assertTrue(decision.motion_allowed)

    def test_48_web_video_unavailable_blocks_motion(self):
        decision = guardian().evaluate(inputs(
            command="SLOW_DOWN", throttle_percent=10.0, web_video_available=False,
        ))
        self.assertEqual(decision.status, "ABORTED")
        self.assertEqual(decision.abort_reason, "BLOCKED_UNEXPECTED_ARM")
        self.assertFalse(decision.motion_allowed)

    def test_49_web_video_and_all_gates_allow_readiness_not_motion(self):
        decision = guardian_waiting_for_arm().evaluate(inputs(web_video_available=True))
        self.assertEqual(decision.status, "READY_FOR_OBSTACLE_TEST")
        self.assertTrue(decision.actuator_path_ready)
        self.assertFalse(decision.motion_allowed)

    def test_50_fake_transport_never_opens_a_network_connection(self):
        transport = FakeTransport()
        core = AdapterCore(session_id="fake")
        actions = core.update("SLOW_DOWN", 0.1, 0.1, True, now=1.0)
        publish_actions(transport, actions)
        self.assertEqual(len(transport.published), 1)

    def test_51_hardware_script_owns_only_its_web_video_pid(self):
        text = HARDWARE_SCRIPT.read_text()
        self.assertIn('WEB_VIDEO_PID_FILE="${SESSION_DIR}/web_video_server.pid"', text)
        self.assertIn('kill "$WEB_VIDEO_PID"', text)
        self.assertNotIn("pkill", text)
        self.assertNotIn("killall", text)
        self.assertNotIn("mosquitto_pub", text)
        self.assertNotIn("/tmp", text)

    def test_52_launch_exposes_bounded_startup_grace_and_hud_gate(self):
        text = LAUNCH.read_text()
        self.assertIn(
            'DeclareLaunchArgument("hardware_test_startup_grace_period_s", default_value="8.0")',
            text,
        )
        self.assertIn(
            'DeclareLaunchArgument("hardware_test_web_video_available", default_value="false")',
            text,
        )

    def test_53_auto_mode_waits_for_operator_mode_while_disarmed(self):
        decision = guardian().evaluate(inputs(fcu_armed=False, fcu_mode="AUTO"))
        self.assertEqual(decision.status, "WAITING_FOR_OPERATOR_MODE")
        self.assertEqual(decision.abort_reason, "")
        self.assertFalse(decision.motion_allowed)

    def test_54_operator_auto_to_manual_transition_is_accepted_disarmed(self):
        core = guardian()
        waiting_mode = core.evaluate(inputs(fcu_armed=False, fcu_mode="AUTO"))
        waiting_arm = core.evaluate(inputs(fcu_armed=False, fcu_mode="MANUAL"))
        self.assertEqual(waiting_mode.status, "WAITING_FOR_OPERATOR_MODE")
        self.assertEqual(waiting_arm.status, "WAITING_FOR_OPERATOR_ARM")
        self.assertFalse(core.aborted)

    def test_55_hardware_test_never_changes_mode_or_arms(self):
        text = "\n".join((
            HARDWARE_SCRIPT.read_text(),
            ADAPTER_NODE.read_text(),
            GUARDIAN_NODE.read_text(),
        ))
        self.assertNotIn("/mavros/set_mode", text)
        self.assertNotIn("/mavros/cmd/arming", text)
        self.assertNotIn("CommandBool", text)
        self.assertNotIn("SetMode", text)
        self.assertNotIn("ros2 service call", text)

    def test_56_manual_disarmed_is_waiting_for_operator_arm(self):
        decision = guardian().evaluate(inputs(fcu_armed=False, fcu_mode="MANUAL"))
        self.assertEqual(decision.status, "WAITING_FOR_OPERATOR_ARM")
        self.assertFalse(decision.motion_allowed)

    def test_57_manual_armed_after_prearm_gate_is_ready(self):
        decision = guardian_waiting_for_arm().evaluate(inputs())
        self.assertEqual(decision.status, "READY_FOR_OBSTACLE_TEST")
        self.assertTrue(decision.actuator_path_ready)
        self.assertFalse(decision.motion_allowed)

    def test_58_armed_in_auto_is_blocked_unexpected_arm(self):
        decision = guardian().evaluate(inputs(fcu_mode="AUTO", fcu_armed=True))
        self.assertEqual(decision.abort_reason, "BLOCKED_UNEXPECTED_ARM")
        self.assertFalse(decision.motion_allowed)

    def test_59_armed_without_guardian_heartbeat_cannot_be_ready(self):
        core = guardian_waiting_for_arm()
        decision = core.evaluate(inputs(guardian_heartbeat_fresh=False))
        self.assertEqual(decision.status, "WAITING_FOR_CA_READY")
        self.assertFalse(decision.motion_allowed)

    def test_60_hold_course_after_ready_does_not_send_motion(self):
        decision = guardian_waiting_for_arm().evaluate(inputs(command="HOLD_COURSE"))
        self.assertEqual(decision.status, "READY_FOR_OBSTACLE_TEST")
        self.assertFalse(decision.motion_allowed)

    def test_61_mode_change_during_motion_neutral_releases_and_aborts(self):
        guardian_core = guardian_waiting_for_arm()
        moving = guardian_core.evaluate(inputs(
            command="SLOW_DOWN", throttle_percent=10.0,
        ))
        adapter_core = AdapterCore(session_id="fake")
        adapter_core.update("SLOW_DOWN", 0.1, 0.1, moving.motion_allowed, now=1.0)
        aborted = guardian_core.evaluate(inputs(
            now=10.1, adapter_heartbeat_at=10.1, command_at=10.1,
            safe_command_at=10.1, command="SLOW_DOWN", throttle_percent=10.0,
            fcu_mode="AUTO",
        ))
        actions = adapter_core.update("SLOW_DOWN", 0.1, 0.1, False, now=1.1)
        self.assertEqual(aborted.abort_reason, "FCU_MODE_CHANGED")
        self.assertEqual([action.kind for action in actions], ["NEUTRAL"] * 3 + ["RELEASE"] * 3)

    def test_62_disarm_during_motion_releases_and_aborts(self):
        guardian_core = guardian_waiting_for_arm()
        moving = guardian_core.evaluate(inputs(
            command="TURN_RIGHT", throttle_percent=10.0, steering_percent=15.0,
        ))
        adapter_core = AdapterCore(session_id="fake")
        adapter_core.update("TURN_RIGHT", 0.25, -0.05, moving.motion_allowed, now=1.0)
        aborted = guardian_core.evaluate(inputs(
            now=10.1, adapter_heartbeat_at=10.1, command_at=10.1,
            safe_command_at=10.1, command="TURN_RIGHT", throttle_percent=10.0,
            steering_percent=15.0, fcu_armed=False,
        ))
        actions = adapter_core.update("TURN_RIGHT", 0.25, -0.05, False, now=1.1)
        self.assertEqual(aborted.abort_reason, "FCU_DISARMED_AFTER_READY")
        self.assertEqual([action.kind for action in actions], ["NEUTRAL"] * 3 + ["RELEASE"] * 3)

    def test_63_required_mode_is_explicitly_manual(self):
        launch_text = LAUNCH.read_text()
        script_text = HARDWARE_SCRIPT.read_text()
        self.assertIn(
            'DeclareLaunchArgument("hardware_test_required_fcu_mode", default_value="MANUAL")',
            launch_text,
        )
        self.assertIn('REQUIRED_FCU_MODE="${CA_TEST_REQUIRED_FCU_MODE:-MANUAL}"', script_text)
        self.assertNotIn("hardware_test_expected_fcu_mode", script_text)

    def test_64_armed_without_live_hud_does_not_allow_motion(self):
        core = guardian()
        self.assertEqual(
            core.evaluate(inputs(fcu_armed=False)).status,
            "WAITING_FOR_OPERATOR_ARM",
        )
        decision = core.evaluate(inputs(
            now=10.1,
            adapter_heartbeat_at=10.1,
            command_at=10.1,
            safe_command_at=10.1,
            command="SLOW_DOWN",
            throttle_percent=10.0,
            hud_heartbeat_fresh=False,
        ))
        self.assertEqual(decision.status, "WAITING_FOR_CA_READY")
        self.assertEqual(decision.blocked_reason, "HUD_HEARTBEAT_STALE")
        self.assertFalse(decision.motion_allowed)

    def test_65_slow_down_never_inherits_transient_steering(self):
        self.assertEqual(
            command_to_test_output("SLOW_DOWN", 0.25, 0.05, Limits())[:2],
            (10.0, 0.0),
        )

    def test_66_turn_direction_follows_command_not_transient_input(self):
        left = command_to_test_output("TURN_LEFT", 0.05, 0.25, Limits())
        right = command_to_test_output("TURN_RIGHT", 0.25, 0.05, Limits())
        self.assertLess(left[1], 0.0)
        self.assertGreater(right[1], 0.0)

    def test_67_hud_heartbeat_and_hardware_overlay_are_required(self):
        hud = HUD_NODE.read_text()
        script = HARDWARE_SCRIPT.read_text()
        self.assertIn('"/ca/hardware_test/hud_heartbeat"', hud)
        self.assertIn('HUD_TOPIC="/ca/hardware_test/debug_image"', script)

    def test_68_motion_sent_is_based_on_adapter_publish(self):
        adapter = ADAPTER_NODE.read_text()
        guardian_source = GUARDIAN_NODE.read_text()
        self.assertIn('"MOTION_COMMAND_SENT"', adapter)
        self.assertIn('"/ca/hardware_test/motion_command_sent"', adapter)
        self.assertNotIn(
            'create_publisher(Bool, "/ca/hardware_test/motion_command_sent"',
            guardian_source,
        )

    def test_69_future_evidence_logs_mqtt_echo_and_rc_observation(self):
        adapter = ADAPTER_NODE.read_text()
        self.assertIn('"OWN_MQTT_ECHO"', adapter)
        self.assertIn('"RC_OVERRIDE_OBSERVED_AFTER_MQTT"', adapter)
        self.assertIn(
            'create_subscription(OverrideRCIn, "/mavros/rc/override"',
            adapter,
        )
        self.assertNotIn("create_publisher(OverrideRCIn", adapter)

    def test_70_hold_is_allowed_only_for_controlled_neutral_release(self):
        adapter = ADAPTER_NODE.read_text()
        self.assertIn(
            'self.command in ("STOP", "HOLD_COURSE")',
            adapter,
        )

    def test_71_tests_use_fake_transport_not_real_broker(self):
        test_source = Path(__file__).read_text()
        mqtt_import = "from seano_vision.thruster_test_" + "mqtt import"
        network_connect = "client." + "connect"
        self.assertNotIn(mqtt_import, test_source)
        self.assertNotIn(network_connect, test_source)

    def test_72_disarm_releases_even_after_prior_control_was_released(self):
        core = AdapterCore(session_id="fake")
        core.update("SLOW_DOWN", 0.1, 0.1, True, now=1.0)
        self.assertEqual(
            [action.kind for action in core.update(
                "HOLD_COURSE", 0.0, 0.0, True, now=1.1
            )],
            ["NEUTRAL", "RELEASE"],
        )
        actions = core.update(
            "HOLD_COURSE", 0.0, 0.0, False, now=1.2
        )
        self.assertEqual(
            [action.kind for action in actions],
            ["NEUTRAL"] * 3 + ["RELEASE"] * 3,
        )


if __name__ == "__main__":
    unittest.main()
