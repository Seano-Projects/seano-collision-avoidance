"""Pure/fake tests for the dedicated AUTO takeover runtime."""

import hashlib
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import textwrap
import time

import numpy as np
import yaml

from seano_vision.auto_takeover_hud import (
    HEADER_HEIGHT,
    header_lines,
    render_auto_takeover_header,
)
from seano_vision.auto_takeover_state import (
    AutoTakeoverCore,
    AutoTakeoverInputs,
    RcCycleEvidence,
    classify_slow_effectiveness,
)
from seano_vision.thruster_test_safety import (
    ACTIVE_FOREIGN_COMMAND,
    AdapterCore,
    OwnMessageRegistry,
    TestLimits as SafetyLimits,
    classify_mqtt_message,
    canonical_thruster_mapping,
    command_to_test_output,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "seano_ca_ws" / "run_pool_auto_takeover_test.sh"
BASELINE = REPO_ROOT / "seano_ca_ws" / "run_pool_existing_control_path.sh"
MANUAL = REPO_ROOT / "seano_ca_ws" / "run_pool_thruster_hardware_test.sh"
LAUNCH = PACKAGE_ROOT / "launch" / "auto_takeover_test.launch.py"
MANAGER = PACKAGE_ROOT / "seano_vision" / "auto_takeover_manager_node.py"


def ready(now=10.0, **overrides):
    values = dict(
        now=now,
        fcu_connected=True,
        fcu_armed=True,
        fcu_mode="AUTO",
        software_ready=True,
        perception_valid=True,
        perception_state="NORMAL",
        camera_perception_available=True,
        manager_fresh=True,
        watchdog_fresh=True,
        risk_policy_valid=True,
        command_fresh=True,
        failsafe_active=False,
        desired_command="HOLD_COURSE",
        safe_command="HOLD_COURSE",
        selected_command="HOLD_COURSE",
        mqtt_connected=True,
        web_video_available=True,
        adapter_fresh=True,
        hud_fresh=True,
        rc_publisher_count=1,
        rc_publisher_name="/usv/thruster",
        rc_subscriber_present=True,
        release_echo_received=False,
        rc_neutral_confirmed=False,
        command_delivery_fresh=True,
        command_delivery_age_s=0.0,
        mission_status_known=False,
        mission_active=True,
    )
    values.update(overrides)
    return AutoTakeoverInputs(**values)


def monitoring():
    core = AutoTakeoverCore(started_at=0.0)
    core.step(ready(8.0, fcu_armed=False))
    core.step(ready(8.1, fcu_armed=False))
    core.step(ready(8.2, fcu_armed=False))
    core.step(ready(8.3))
    assert core.state == "AUTO_MISSION_MONITORING"
    return core


def manual_ready(command="SLOW_DOWN"):
    core = monitoring()
    core.step(ready(9.0, selected_command=command))
    core.step(ready(9.5, selected_command=command))
    assert core.consume_mode_request() == "MANUAL"
    core.step(ready(9.6, selected_command=command))
    core.report_mode_request("MANUAL", True)
    core.step(ready(9.7, fcu_mode="MANUAL", selected_command=command))
    output = core.step(ready(9.8, fcu_mode="MANUAL", selected_command=command))
    assert output.state == "MOTION_COMMAND_PENDING"
    assert core.motion_started_at == 0.0
    output = core.step(ready(
        9.9,
        fcu_mode="MANUAL",
        selected_command=command,
        motion_command_sent=True,
    ))
    assert output.state == "MOTION_ACTIVE"
    return core


def test_01_auto_hold_does_not_request_mode():
    core = monitoring()
    core.step(ready(20.0))
    assert core.consume_mode_request() == ""


def test_02_auto_hold_does_not_allow_mqtt_motion():
    assert not monitoring().step(ready(20.0)).motion_allowed


def test_03_stable_hazard_requests_manual_once():
    core = monitoring()
    core.step(ready(20.0, selected_command="SLOW_DOWN"))
    core.step(ready(20.5, selected_command="SLOW_DOWN"))
    assert core.consume_mode_request() == "MANUAL"
    assert core.consume_mode_request() == ""


def test_04_no_motion_before_manual_confirmation():
    core = monitoring()
    core.step(ready(20.0, selected_command="TURN_LEFT"))
    output = core.step(ready(20.5, selected_command="TURN_LEFT"))
    assert not output.motion_allowed


def test_05_manual_service_failure_blocks_motion():
    core = monitoring()
    core.step(ready(20.0, selected_command="STOP"))
    core.step(ready(20.5, selected_command="STOP"))
    core.report_mode_request("MANUAL", False)
    assert core.state == "ABORTED"
    assert not core.output(ready(20.6)).motion_allowed


def test_06_manual_confirmation_timeout_aborts():
    core = monitoring()
    core.step(ready(20.0, selected_command="STOP"))
    core.step(ready(20.5, selected_command="STOP"))
    core.step(ready(20.6, selected_command="STOP"))
    core.step(ready(24.0, selected_command="STOP"))
    assert core.abort_reason == "ABORTED_MODE_CHANGE_TIMEOUT"


def test_07_manual_and_all_gates_allow_motion():
    assert manual_ready().output(ready(10.0, fcu_mode="MANUAL")).motion_allowed


def test_08_slow_down_mapping_is_conservative():
    assert command_to_test_output("SLOW_DOWN", 0.5, 0.5, AdapterCore().limits)[:2] == (10.0, 0.0)


def test_09_turn_left_steering_is_negative():
    assert command_to_test_output("TURN_LEFT", 0.2, 0.8, AdapterCore().limits)[1] < 0


def test_10_turn_right_steering_is_positive():
    assert command_to_test_output("TURN_RIGHT", 0.8, 0.2, AdapterCore().limits)[1] > 0


def test_11_stop_is_neutral():
    assert command_to_test_output("STOP", 1.0, 1.0, AdapterCore().limits)[:2] == (0.0, 0.0)


def test_12_one_clear_frame_does_not_restore_auto():
    core = manual_ready()
    output = core.step(ready(10.0, fcu_mode="MANUAL"))
    assert output.state == "CLEAR_HOLD"
    assert core.consume_mode_request() == ""


def test_13_stable_clear_requests_bounded_release():
    core = manual_ready()
    core.step(ready(10.0, fcu_mode="MANUAL"))
    output = core.step(ready(12.6, fcu_mode="MANUAL"))
    assert output.state == "NEUTRALIZING"
    assert output.hardware_command == "STOP"
    output = core.step(ready(
        12.7,
        fcu_mode="MANUAL",
        neutral_sent=True,
        rc_neutral_confirmed=True,
    ))
    assert output.state == "RELEASING_CONTROL"
    assert output.hardware_command == "HOLD_COURSE"


def test_14_auto_requested_only_after_release():
    core = manual_ready()
    core.step(ready(10.0, fcu_mode="MANUAL"))
    core.step(ready(12.6, fcu_mode="MANUAL"))
    assert core.consume_mode_request() == ""
    core.step(ready(
        12.7,
        fcu_mode="MANUAL",
        neutral_sent=True,
        rc_neutral_confirmed=True,
    ))
    core.step(ready(
        12.8,
        fcu_mode="MANUAL",
        neutral_sent=True,
        rc_neutral_confirmed=True,
        release_sent=True,
        release_echo_received=True,
    ))
    assert core.consume_mode_request() == "AUTO"


def test_15_auto_restore_requires_takeover_owner():
    core = manual_ready()
    core.takeover_owner = False
    core.state = "RELEASING_CONTROL"
    core.step(ready(
        12.7,
        fcu_mode="MANUAL",
        neutral_sent=True,
        release_sent=True,
        release_echo_received=True,
    ))
    assert core.abort_reason == "AUTO_RESTORE_NOT_OWNED"


def test_16_operator_mode_intervention_does_not_force_auto():
    core = manual_ready()
    core.step(ready(10.0, fcu_mode="RTL", selected_command="SLOW_DOWN"))
    assert core.abort_reason == "OPERATOR_MODE_INTERVENTION"
    assert core.consume_mode_request() == ""


def test_17_restore_auto_service_failure_is_recoverable():
    core = manual_ready()
    core.step(ready(10.0, fcu_mode="MANUAL"))
    core.step(ready(12.6, fcu_mode="MANUAL"))
    core.step(ready(
        12.7,
        fcu_mode="MANUAL",
        neutral_sent=True,
        rc_neutral_confirmed=True,
    ))
    core.step(ready(
        12.8,
        fcu_mode="MANUAL",
        neutral_sent=True,
        release_sent=True,
        release_echo_received=True,
    ))
    assert core.consume_mode_request() == "AUTO"
    core.report_mode_request("AUTO", False)
    assert core.state == "AUTO_RESTORE_RETRY"
    assert core.abort_reason == ""


def test_18_disarm_during_motion_aborts():
    core = manual_ready()
    core.step(ready(10.0, fcu_mode="MANUAL", fcu_armed=False, selected_command="SLOW_DOWN"))
    assert core.abort_reason == "FCU_DISARMED"


def test_19_perception_lost_during_motion_switches_to_stop():
    core = manual_ready()
    output = core.step(ready(
        10.0,
        fcu_mode="MANUAL",
        perception_valid=False,
        selected_command="SLOW_DOWN",
    ))
    assert output.state == "MOTION_COMMAND_PENDING"
    assert output.hardware_command == "STOP"
    assert output.command_publish_allowed
    assert not output.motion_allowed


def test_20_foreign_active_command_aborts():
    core = manual_ready()
    core.step(ready(10.0, fcu_mode="MANUAL", foreign_active=True, selected_command="SLOW_DOWN"))
    assert core.abort_reason == "FOREIGN_ACTIVE_COMMAND"


def test_21_own_mqtt_echo_is_not_active_foreign():
    registry = OwnMessageRegistry()
    action = AdapterCore(session_id="own").update("STOP", 0, 0, True, now=1.0)[0]
    raw = __import__("json").dumps(action.payload, separators=(",", ":"), sort_keys=True)
    import hashlib
    registry.register(action, hashlib.sha256(raw.encode()).hexdigest())
    assert classify_mqtt_message(raw, own_registry=registry).classification != ACTIVE_FOREIGN_COMMAND


def test_22_rc_publisher_change_aborts():
    core = manual_ready()
    core.step(ready(10.0, fcu_mode="MANUAL", rc_publisher_name="/other", selected_command="SLOW_DOWN"))
    assert core.abort_reason == "RC_PATH_CHANGED"


def test_23_fresh_motion_continues_beyond_old_two_second_limit():
    core = manual_ready()
    output = core.step(ready(
        12.0,
        fcu_mode="MANUAL",
        selected_command="SLOW_DOWN",
        mqtt_ack_received=True,
    ))
    assert output.state == "MOTION_ACTIVE"
    assert output.motion_allowed
    assert not output.abort_reason


def test_24_mode_request_has_no_infinite_retry():
    core = monitoring()
    core.step(ready(20.0, selected_command="STOP"))
    core.step(ready(20.5, selected_command="STOP"))
    assert core.mode_request_count == 1
    core.step(ready(21.0, selected_command="STOP"))
    assert core.mode_request_count == 1


def test_25_aborted_state_has_no_motion_retry():
    core = manual_ready()
    core.step(ready(10.0, fcu_mode="MANUAL", fcu_armed=False, selected_command="SLOW_DOWN"))
    for now in (11.0, 12.0, 20.0):
        assert not core.step(ready(now, fcu_mode="MANUAL")).motion_allowed


def test_26_baseline_remains_no_hardware():
    text = BASELINE.read_text()
    assert "hardware_output_enabled:=false" in text
    assert "use_guarded_thruster_test_adapter:=false" in text


def test_27_manual_hardware_runtime_remains_separate():
    assert "TYPE: ENABLE GUARDED THRUSTER TEST" in MANUAL.read_text()
    assert "AUTO TAKEOVER" not in MANUAL.read_text()


def test_28_auto_runtime_starts_no_mavros_or_rc_bridge():
    text = LAUNCH.read_text()
    assert '"use_mavros": "false"' in text
    assert '"use_rc_override_bridge": "false"' in text
    assert '"use_mode_manager": "false"' in text


def test_29_manager_has_no_rc_override_publisher():
    text = MANAGER.read_text()
    assert "create_publisher(OverrideRCIn" not in text
    assert 'create_subscription(\n            OverrideRCIn, "/mavros/rc/override"' in text


def test_30_tests_use_no_real_broker():
    text = Path(__file__).read_text()
    assert "paho." + "mqtt" not in text
    assert ".con" + "nect(" not in text


def test_31_manager_has_no_arm_or_disarm_service():
    text = MANAGER.read_text()
    assert "CommandBool" not in text
    assert "/mavros/cmd/arming" not in text


def test_32_dry_check_has_no_ros_or_mqtt_runtime():
    result = subprocess.run([str(SCRIPT), "--dry-check"], text=True, capture_output=True)
    assert result.returncode == 0
    assert "No ROS node started" in result.stdout
    assert "No MQTT connection opened" in result.stdout


def test_33_runtime_logs_are_scoped_inside_repo():
    text = SCRIPT.read_text()
    assert 'case "$RUNTIME_ROOT" in "$REPO_ROOT"|"$REPO_ROOT"/*)' in text
    assert "POOL_AUTO_TAKEOVER_TEST_" in text


def test_34_shutdown_uses_no_global_kill():
    text = SCRIPT.read_text()
    assert "pkill" not in text
    assert "killall" not in text
    assert "systemctl" not in text


def test_35_hud_adds_header_without_touching_baseline_pixels():
    frame = np.arange(480 * 640 * 3, dtype=np.uint8).reshape((480, 640, 3))
    original = frame.copy()
    output = render_auto_takeover_header(frame, {"state": "AUTO_MISSION_MONITORING"})
    assert output.shape == (480 + HEADER_HEIGHT, 640, 3)
    assert np.array_equal(output[HEADER_HEIGHT:], original)
    assert np.array_equal(frame, original)


def test_36_fake_preflight_is_read_only():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        credentials = root / "mqtt.yaml"
        credentials.write_text(yaml.safe_dump({
            "/**": {"ros__parameters": {
                "mqtt": {
                    "host": "fake.invalid", "port": 8883,
                    "username": "fake-user", "password": "fake-password",
                    "tls": True, "tls_insecure": False,
                }
            }}
        }))
        fake_bin = root / "bin"
        fake_bin.mkdir()
        calls = root / "calls"
        ros2 = fake_bin / "ros2"
        ros2.write_text(textwrap.dedent("""\
            #!/usr/bin/env bash
            printf '%s\\n' "$*" >> "$FAKE_CALLS"
            case "$*" in
              "node list") printf '/usv/thruster\\n' ;;
              "topic echo /mavros/state --once") printf 'connected: true\\narmed: false\\nmode: AUTO\\n' ;;
              "topic info -v /mavros/rc/override")
                printf 'Publisher count: 1\\nNode name: thruster\\nNode namespace: /usv\\n'
                printf 'Subscription count: 1\\nNode name: rc\\nNode namespace: /mavros\\n' ;;
              "service list") printf '/mavros/set_mode\\n' ;;
              *) exit 90 ;;
            esac
        """))
        ros2.chmod(ros2.stat().st_mode | stat.S_IXUSR)
        env = dict(
            os.environ,
            PATH=f"{fake_bin}:{os.environ['PATH']}",
            SEANO_MQTT_ENV_FILE=str(credentials),
            FAKE_CALLS=str(calls),
            ROS_DOMAIN_ID="0",
        )
        result = subprocess.run(
            [str(SCRIPT), "--preflight-only"],
            env=env, text=True, capture_output=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        called = calls.read_text()
        assert " launch " not in f" {called} "
        assert " service call " not in f" {called} "
        assert "Ready for guarded AUTO takeover procedure: true" in result.stdout


def _run_sourced_script(body, *, extra_env=None):
    env = dict(os.environ, AUTO_SCRIPT=str(SCRIPT))
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", "-c", 'source "$AUTO_SCRIPT"\n' + body],
        env=env,
        text=True,
        capture_output=True,
    )


def test_37_empty_port_starts_and_owns_fake_session_server():
    with tempfile.TemporaryDirectory() as directory:
        result = _run_sourced_script(textwrap.dedent("""\
            WEB_VIDEO_PORT=18080
            WEB_VIDEO_BIND_ADDRESS=0.0.0.0
            WEB_VIDEO_LOG="$FAKE_DIR/web.log"
            WEB_VIDEO_PID_FILE="$FAKE_DIR/web.pid"
            WEB_VIDEO_START_ATTEMPTS=1
            WEB_VIDEO_START_INTERVAL_S=0
            web_video_package_available() { return 0; }
            web_video_spawn() { sleep 30 & WEB_VIDEO_PID=$!; }
            web_video_port_listening() { [ -n "${WEB_VIDEO_PID:-}" ] && kill -0 "$WEB_VIDEO_PID"; }
            web_video_non_loopback_listener() { return 0; }
            web_video_http_healthy() { return 0; }
            start_web_video_server
            owned_pid="$WEB_VIDEO_PID"
            [ "$WEB_VIDEO_AVAILABLE" = true ]
            [ "$WEB_VIDEO_STARTED_BY_SCRIPT" -eq 1 ]
            [ "$(cat "$WEB_VIDEO_PID_FILE")" = "$owned_pid" ]
            cleanup_session
            ! kill -0 "$owned_pid" 2>/dev/null
        """), extra_env={"FAKE_DIR": directory})
        assert result.returncode == 0, result.stdout + result.stderr


def test_38_healthy_existing_fake_server_is_reused_without_ownership():
    result = _run_sourced_script(textwrap.dedent("""\
        sleep 30 &
        existing_pid=$!
        WEB_VIDEO_PORT=18080
        WEB_VIDEO_BIND_ADDRESS=0.0.0.0
        web_video_port_listening() { return 0; }
        web_video_non_loopback_listener() { return 0; }
        web_video_http_healthy() { return 0; }
        start_web_video_server
        [ "$WEB_VIDEO_AVAILABLE" = true ]
        [ "$WEB_VIDEO_STARTED_BY_SCRIPT" -eq 0 ]
        cleanup_session
        kill -0 "$existing_pid"
        kill "$existing_pid"
        wait "$existing_pid" 2>/dev/null || true
    """))
    assert result.returncode == 0, result.stdout + result.stderr


def test_39_failed_fake_server_start_is_stopped_and_fail_closed():
    with tempfile.TemporaryDirectory() as directory:
        result = _run_sourced_script(textwrap.dedent("""\
            WEB_VIDEO_PORT=18080
            WEB_VIDEO_BIND_ADDRESS=0.0.0.0
            WEB_VIDEO_LOG="$FAKE_DIR/web.log"
            WEB_VIDEO_PID_FILE="$FAKE_DIR/web.pid"
            WEB_VIDEO_START_ATTEMPTS=1
            WEB_VIDEO_START_INTERVAL_S=0
            web_video_package_available() { return 0; }
            web_video_spawn() { sleep 30 & WEB_VIDEO_PID=$!; FAILED_PID=$WEB_VIDEO_PID; }
            web_video_port_listening() { return 1; }
            web_video_non_loopback_listener() { return 1; }
            web_video_http_healthy() { return 1; }
            start_web_video_server
            [ "$WEB_VIDEO_AVAILABLE" = false ]
            [ "$WEB_VIDEO_BLOCKED_REASON" = HUD_WEB_VIDEO_UNAVAILABLE ]
            ! kill -0 "$FAILED_PID" 2>/dev/null
        """), extra_env={"FAKE_DIR": directory})
        assert result.returncode == 0, result.stdout + result.stderr


def test_40_web_server_bind_and_operator_url_are_non_loopback_auto_hud():
    text = SCRIPT.read_text()
    assert 'WEB_VIDEO_BIND_ADDRESS="0.0.0.0"' in text
    assert '-p address:="${WEB_VIDEO_BIND_ADDRESS}"' in text
    assert "topic=${HUD_TOPIC}" in text
    assert 'HUD_TOPIC="/ca/auto_takeover/debug_image"' in text


def test_41_startup_lost_perception_waits_without_abort_or_mode_request():
    core = AutoTakeoverCore(started_at=0.0)
    output = core.step(ready(
        8.0,
        fcu_armed=False,
        software_ready=False,
        perception_valid=False,
        failsafe_active=True,
    ))
    assert output.state == "WAITING_FOR_CA_READY"
    assert not output.motion_allowed
    assert not output.actuator_path_ready
    assert not output.abort_reason
    assert core.consume_mode_request() == ""


def test_42_startup_stale_command_and_failsafe_keep_waiting():
    core = AutoTakeoverCore(started_at=0.0)
    core.step(ready(
        8.0,
        fcu_armed=False,
        software_ready=False,
        command_fresh=False,
        failsafe_active=True,
    ))
    output = core.step(ready(
        20.0,
        fcu_armed=False,
        software_ready=False,
        command_fresh=False,
        failsafe_active=True,
    ))
    assert output.state == "WAITING_FOR_CA_READY"
    assert output.blocked_reason == "CA_NOT_READY"
    assert not output.abort_reason


def test_43_unavailable_web_blocks_startup_mode_and_actuator_path():
    core = AutoTakeoverCore(started_at=0.0)
    output = core.step(ready(
        8.0,
        fcu_armed=False,
        software_ready=False,
        web_video_available=False,
    ))
    assert output.state == "WAITING_FOR_CA_READY"
    assert output.blocked_reason == "HUD_WEB_VIDEO_UNAVAILABLE"
    assert not output.motion_allowed
    assert not output.actuator_path_ready
    assert core.consume_mode_request() == ""


def test_44_fault_after_control_was_ready_switches_to_stop_takeover():
    core = manual_ready()
    output = core.step(ready(
        10.0,
        fcu_mode="MANUAL",
        failsafe_active=True,
        selected_command="SLOW_DOWN",
    ))
    assert output.state == "MOTION_COMMAND_PENDING"
    assert output.hardware_command == "STOP"
    assert output.command_publish_allowed
    assert not output.motion_allowed


def test_45_owned_launch_helper_waits_for_fake_launch_and_logs_output():
    with tempfile.TemporaryDirectory() as directory:
        started = time.monotonic()
        result = _run_sourced_script(textwrap.dedent("""\
            TERMINAL_LOG="$FAKE_DIR/terminal.log"
            TERMINAL_PIPE="$FAKE_DIR/terminal.pipe"
            run_owned_ros_launch bash -c 'sleep 0.25; echo fake-launch-complete'
            grep -q fake-launch-complete "$TERMINAL_LOG"
        """), extra_env={"FAKE_DIR": directory})
        elapsed = time.monotonic() - started
        assert result.returncode == 0, result.stdout + result.stderr
        assert elapsed >= 0.20


def test_46_web_unavailable_is_forwarded_to_manager_launch_gate():
    script = SCRIPT.read_text()
    launch = LAUNCH.read_text()
    manager = MANAGER.read_text()
    assert 'web_video_available:="$WEB_VIDEO_AVAILABLE"' in script
    assert 'DeclareLaunchArgument("web_video_available", default_value="false")' in launch
    assert '("web_video_available", False)' in manager


def _finish_clear_release_auto(core, *, clear_at, release_at):
    clear = core.step(ready(clear_at, fcu_mode="MANUAL"))
    assert clear.state == "CLEAR_HOLD"
    releasing = core.step(ready(release_at, fcu_mode="MANUAL"))
    assert releasing.state == "NEUTRALIZING"
    assert core.consume_mode_request() == ""
    releasing = core.step(ready(
        release_at + 0.1,
        fcu_mode="MANUAL",
        neutral_sent=True,
        rc_neutral_confirmed=True,
    ))
    assert releasing.state == "RELEASING_CONTROL"
    requested = core.step(ready(
        release_at + 0.2,
        fcu_mode="MANUAL",
        neutral_sent=True,
        rc_neutral_confirmed=True,
        release_sent=True,
        release_echo_received=True,
    ))
    assert requested.state == "AUTO_RESTORE_REQUESTED"
    assert core.consume_mode_request() == "AUTO"
    core.report_mode_request("AUTO", True)
    waiting = core.step(ready(
        release_at + 0.3,
        fcu_mode="MANUAL",
        neutral_sent=True,
        release_sent=True,
        release_echo_received=True,
    ))
    assert waiting.state == "WAITING_FOR_AUTO_CONFIRMATION"
    confirmed = core.step(ready(
        release_at + 0.4,
        fcu_mode="AUTO",
        neutral_sent=True,
        release_sent=True,
        release_echo_received=True,
    ))
    assert confirmed.state == "AUTO_REJOIN_VERIFY"
    confirmed = core.step(ready(
        release_at + 1.0,
        fcu_mode="AUTO",
        neutral_sent=True,
        release_sent=True,
        release_echo_received=True,
    ))
    assert confirmed.state == "AUTO_CONFIRMED"
    monitoring_output = core.step(ready(
        release_at + 1.1,
        fcu_mode="AUTO",
        neutral_sent=True,
        release_sent=True,
    ))
    assert monitoring_output.state == "AUTO_MISSION_MONITORING"
    return monitoring_output


def test_47_hazard_clears_before_limit_releases_and_restores_auto():
    core = manual_ready()
    output = _finish_clear_release_auto(core, clear_at=10.0, release_at=12.6)
    assert output.state == "AUTO_MISSION_MONITORING"
    assert core.auto_confirmed_at == 0.0
    assert core.last_completed_cycle["auto_confirmed_time"] > 0.0


def test_48_hazard_clears_exactly_at_two_seconds_without_abort():
    core = manual_ready()
    output = core.step(ready(11.8, fcu_mode="MANUAL"))
    assert output.state == "CLEAR_HOLD"
    assert not output.abort_reason
    assert not core.motion_limit_reached


def test_49_stale_delivery_enters_neutral_wait_without_motion():
    core = manual_ready()
    output = core.step(ready(
        11.8,
        fcu_mode="MANUAL",
        selected_command="TURN_LEFT",
        command_delivery_fresh=False,
        command_delivery_age_s=2.01,
    ))
    assert output.state == "SAFE_NEUTRAL_WAIT_CLEAR"
    assert output.hardware_command == "STOP"
    assert not output.motion_allowed
    assert output.actuator_path_ready
    events = [event["event"] for event in core.consume_events()]
    assert "SAFE_NEUTRAL_WAIT_CLEAR" in events


def test_50_hazard_clears_after_watchdog_stop_then_restores_auto():
    core = manual_ready()
    core.step(ready(
        11.8,
        fcu_mode="MANUAL",
        selected_command="SLOW_DOWN",
        command_delivery_fresh=False,
        command_delivery_age_s=2.01,
        neutral_sent=True,
    ))
    output = _finish_clear_release_auto(core, clear_at=12.0, release_at=14.6)
    assert output.state == "AUTO_MISSION_MONITORING"


def test_51_persistent_hazard_has_no_total_takeover_abort_when_fresh():
    core = manual_ready()
    core.step(ready(
        11.8,
        fcu_mode="MANUAL",
        selected_command="SLOW_DOWN",
        mqtt_ack_received=True,
    ))
    output = core.step(ready(
        25.0,
        fcu_mode="MANUAL",
        selected_command="SLOW_DOWN",
        mqtt_ack_received=True,
    ))
    assert output.state == "MOTION_ACTIVE"
    assert output.motion_allowed
    assert not output.abort_reason


def test_52_perception_loss_in_neutral_wait_remains_fail_closed():
    core = manual_ready()
    core.step(ready(
        11.8,
        fcu_mode="MANUAL",
        selected_command="SLOW_DOWN",
        command_delivery_fresh=False,
        command_delivery_age_s=2.01,
    ))
    output = core.step(ready(
        12.0,
        fcu_mode="MANUAL",
        selected_command="SLOW_DOWN",
        perception_valid=False,
    ))
    assert output.state == "SAFE_NEUTRAL_WAIT_CLEAR"
    assert output.hardware_command == "STOP"
    assert not output.motion_allowed


def test_53_disarm_in_neutral_wait_aborts():
    core = manual_ready()
    core.step(ready(
        11.8,
        fcu_mode="MANUAL",
        selected_command="SLOW_DOWN",
        command_delivery_fresh=False,
        command_delivery_age_s=2.01,
    ))
    output = core.step(ready(
        12.0,
        fcu_mode="MANUAL",
        fcu_armed=False,
        selected_command="SLOW_DOWN",
    ))
    assert output.state == "ABORTED"
    assert output.abort_reason == "FCU_DISARMED"


def test_54_operator_mode_intervention_never_restores_auto():
    for operator_mode in ("RTL", "HOLD", "LOITER"):
        core = manual_ready()
        core.step(ready(
            11.8,
            fcu_mode="MANUAL",
            selected_command="SLOW_DOWN",
            command_delivery_fresh=False,
            command_delivery_age_s=2.01,
        ))
        output = core.step(ready(
            12.0,
            fcu_mode=operator_mode,
            selected_command="SLOW_DOWN",
        ))
        assert output.state == "ABORTED"
        assert output.abort_reason == "OPERATOR_MODE_INTERVENTION"
        assert core.consume_mode_request() == ""


def test_55_auto_request_waits_for_both_neutral_and_release():
    core = manual_ready()
    core.step(ready(10.0, fcu_mode="MANUAL"))
    core.step(ready(12.6, fcu_mode="MANUAL"))
    core.step(ready(12.7, fcu_mode="MANUAL", release_sent=True))
    assert core.state == "NEUTRALIZING"
    assert core.blocked_reason == "WAIT_NEUTRAL"
    assert core.consume_mode_request() == ""


def test_56_hazard_return_after_watchdog_stop_requires_new_delivery_proof():
    core = manual_ready()
    core.step(ready(
        11.8,
        fcu_mode="MANUAL",
        selected_command="SLOW_DOWN",
        command_delivery_fresh=False,
        command_delivery_age_s=2.01,
    ))
    core.step(ready(12.0, fcu_mode="MANUAL"))
    output = core.step(ready(
        12.2,
        fcu_mode="MANUAL",
        selected_command="TURN_RIGHT",
    ))
    assert output.state == "AVOIDANCE_READY"
    assert not output.motion_allowed
    output = core.step(ready(
        12.3,
        fcu_mode="MANUAL",
        selected_command="TURN_RIGHT",
    ))
    assert output.state == "MOTION_COMMAND_PENDING"
    assert not output.motion_allowed
    output = core.step(ready(
        12.4,
        fcu_mode="MANUAL",
        selected_command="TURN_RIGHT",
        mqtt_ack_received=True,
    ))
    assert output.state == "MOTION_ACTIVE"


def test_57_auto_bounded_stop_neutral_is_finite_manual_default_unchanged():
    auto_adapter = AdapterCore(
        session_id="auto",
        neutral_repetitions=3,
        bounded_stop_neutral=True,
    )
    first = auto_adapter.update("STOP", 0.0, 0.0, True, now=1.0)
    repeated = auto_adapter.update("STOP", 0.0, 0.0, True, now=1.1)
    assert [action.kind for action in first] == ["NEUTRAL"] * 3
    assert repeated == []

    manual_adapter = AdapterCore(session_id="manual")
    assert len(manual_adapter.update("STOP", 0.0, 0.0, True, now=1.0)) == 1
    assert len(manual_adapter.update("STOP", 0.0, 0.0, True, now=1.1)) == 1


def test_58_limits_and_auto_only_bounded_stop_configuration_remain_conservative():
    script = SCRIPT.read_text()
    launch = LAUNCH.read_text()
    manager = MANAGER.read_text()
    adapter = (
        PACKAGE_ROOT
        / "seano_vision"
        / "guarded_thruster_test_adapter_node.py"
    ).read_text()
    phase_launch = (
        PACKAGE_ROOT / "launch" / "phase7_cuav_usb_hardware.launch.py"
    ).read_text()
    manual_script = MANUAL.read_text()
    assert 'CA_AUTO_MAX_MOTION_DURATION_S:-2.0' in script
    assert 'CA_AUTO_COMMAND_FRESHNESS_WATCHDOG_S:-2.0' in script
    assert 'CA_AUTO_THRUSTER_MAPPING_PROFILE:-SEAPORTAL_ACTUAL' in script
    assert 'CA_AUTO_STEERING_CHANNEL_INDEX:-0' in script
    assert 'CA_AUTO_THROTTLE_CHANNEL_INDEX:-2' in script
    assert 'CA_AUTO_CRUISE_REFERENCE_THROTTLE_PERCENT:-100.0' in script
    assert 'CA_AUTO_SLOW_FACTOR:-0.58' in script
    assert 'CA_AUTO_SLOW_THROTTLE_PERCENT:-58.0' in script
    assert 'CA_AUTO_MINIMUM_EFFECTIVE_THROTTLE_PERCENT:-58.0' in script
    assert 'CA_AUTO_TURN_THROTTLE_PERCENT:-0.0' in script
    assert 'CA_AUTO_MAX_THROTTLE_PERCENT:-58.0' in script
    assert 'CA_AUTO_MAX_STEERING_PERCENT:-100.0' in script
    assert '"hardware_test_bounded_stop_neutral": "true"' in launch
    assert '"hardware_test_maximum_allowed_throttle_percent": "58.0"' in launch
    assert '"hardware_test_mapping_profile": mapping_profile' in launch
    assert '"hardware_test_steering_channel_index": steering_channel_index' in launch
    assert '"hardware_test_throttle_channel_index": throttle_channel_index' in launch
    assert '"cruise_reference_throttle_percent", default_value="100.0"' in launch
    assert 'DeclareLaunchArgument("slow_throttle_percent", default_value="58.0")' in launch
    assert '"minimum_effective_throttle_percent", default_value="58.0"' in launch
    assert '"maximum_test_throttle_percent", default_value="58.0"' in launch
    assert 'DeclareLaunchArgument("turn_throttle_percent", default_value="0.0")' in launch
    assert '("mapping_profile", "SEAPORTAL_ACTUAL")' in manager
    assert '("cruise_reference_throttle_percent", 100.0)' in manager
    assert '("slow_throttle_percent", 58.0)' in manager
    assert '("minimum_effective_throttle_percent", 58.0)' in manager
    assert '("turn_throttle_percent", 0.0)' in manager
    assert '("maximum_test_throttle_percent", 58.0)' in manager
    assert '("maximum_steering_percent", 100.0)' in manager
    assert '"hardware_test_bounded_stop_neutral",' in phase_launch
    assert '"hardware_test_maximum_allowed_throttle_percent",' in phase_launch
    assert '"hardware_test_steering_channel_index",' in phase_launch
    assert '"hardware_test_throttle_channel_index",' in phase_launch
    assert '"maximum_allowed_throttle_percent": ParameterValue(' in phase_launch
    assert '("mapping_profile", "LEGACY_CONSERVATIVE")' in adapter
    assert '("maximum_allowed_throttle_percent", 10.0)' in adapter
    assert 'self._p("maximum_allowed_throttle_percent")' in adapter
    assert 'CA_TEST_MAX_THROTTLE_PERCENT:-10.0' in manual_script
    assert 'default_value="false"' in phase_launch


def test_59_required_lifecycle_events_are_emitted_or_logged():
    core = manual_ready()
    _finish_clear_release_auto(core, clear_at=12.0, release_at=14.6)
    events = {record["event"] for record in core.consume_events()}
    assert {
        "MOTION_COMMAND_PENDING",
        "MOTION_DELIVERY_CONFIRMED",
        "CLEAR_HOLD_STARTED",
        "CLEAR_HOLD_COMPLETED",
        "AUTO_RESTORE_REQUEST_SENT",
        "AUTO_MODE_OBSERVED",
        "AUTO_RESTORE_CONFIRMED",
        "AUTO_REJOIN_VERIFY_STARTED",
        "AUTO_REJOIN_VERIFIED",
        "CYCLE_COMPLETED",
        "CYCLE_STATE_RESET",
        "RETURNED_TO_AUTO_MONITORING",
        "TOTAL_TAKEOVER_DURATION",
    } <= events
    manager = MANAGER.read_text()
    assert '"RELEASE_SENT"' in manager


def test_60_neutral_wait_keeps_foreign_mqtt_and_rc_faults_fail_closed():
    scenarios = (
        ({"foreign_active": True}, "FOREIGN_ACTIVE_COMMAND"),
        ({"foreign_unknown": True}, "FOREIGN_UNKNOWN_SCHEMA"),
        ({"retained_foreign": True}, "FOREIGN_RETAINED_MESSAGE"),
        ({"mqtt_connected": False}, "MQTT_DISCONNECTED"),
        ({"rc_publisher_name": "/unexpected"}, "RC_PATH_CHANGED"),
    )
    for overrides, expected in scenarios:
        core = manual_ready()
        core.step(ready(
            11.8,
            fcu_mode="MANUAL",
            selected_command="SLOW_DOWN",
            command_delivery_fresh=False,
            command_delivery_age_s=2.01,
        ))
        output = core.step(ready(
            12.0,
            fcu_mode="MANUAL",
            selected_command="SLOW_DOWN",
            **overrides,
        ))
        assert output.state == "ABORTED"
        assert output.abort_reason == expected


def _start_independent_cycle(core, start, command="TURN_RIGHT_SLOW"):
    core.step(ready(start, selected_command=command))
    takeover = core.step(ready(start + 0.5, selected_command=command))
    assert takeover.state == "TAKEOVER_REQUESTED"
    assert core.consume_mode_request() == "MANUAL"
    first_hazard = core.first_hazard_at
    takeover_started = core.cycle_takeover_started_at
    core.step(ready(start + 0.6, selected_command=command))
    core.report_mode_request("MANUAL", True)
    core.step(ready(
        start + 0.7,
        fcu_mode="MANUAL",
        selected_command=command,
    ))
    motion = core.step(ready(
        start + 0.8,
        fcu_mode="MANUAL",
        selected_command=command,
    ))
    assert motion.state == "MOTION_COMMAND_PENDING"
    motion = core.step(ready(
        start + 0.9,
        fcu_mode="MANUAL",
        selected_command=command,
        mqtt_ack_received=True,
    ))
    assert motion.state == "MOTION_ACTIVE"
    return first_hazard, takeover_started


def _complete_independent_cycle(core, start):
    core.step(ready(start + 1.0, fcu_mode="MANUAL"))
    core.step(ready(start + 3.6, fcu_mode="MANUAL"))
    core.step(ready(
        start + 3.7,
        fcu_mode="MANUAL",
        neutral_sent=True,
        rc_neutral_confirmed=True,
    ))
    core.step(ready(
        start + 3.8,
        fcu_mode="MANUAL",
        neutral_sent=True,
        rc_neutral_confirmed=True,
        release_sent=True,
        release_echo_received=True,
    ))
    assert core.consume_mode_request() == "AUTO"
    core.report_mode_request("AUTO", True)
    core.step(ready(
        start + 3.9,
        fcu_mode="MANUAL",
        neutral_sent=True,
        release_sent=True,
        release_echo_received=True,
    ))
    rejoin = core.step(ready(
        start + 4.0,
        fcu_mode="AUTO",
        neutral_sent=True,
        release_sent=True,
        release_echo_received=True,
    ))
    assert rejoin.state == "AUTO_REJOIN_VERIFY"
    confirmed = core.step(ready(
        start + 4.6,
        fcu_mode="AUTO",
        neutral_sent=True,
        release_sent=True,
        release_echo_received=True,
    ))
    assert confirmed.state == "AUTO_CONFIRMED"
    completed = dict(core.last_completed_cycle)
    monitoring_output = core.step(ready(start + 4.7, fcu_mode="AUTO"))
    assert monitoring_output.state == "AUTO_MISSION_MONITORING"
    return completed


def test_61_completed_cycle_resets_all_current_cycle_state():
    core = monitoring()
    _start_independent_cycle(core, 20.0)
    completed = _complete_independent_cycle(core, 20.0)
    assert completed["cycle_id"] == 1
    assert completed["total_takeover_duration"] >= 0.0
    for field in (
        "first_hazard_at",
        "manual_requested_at",
        "manual_confirmed_at",
        "motion_started_at",
        "motion_pending_at",
        "motion_delivery_confirmed_at",
        "motion_limit_reached_at",
        "clear_started_at",
        "release_started_at",
        "auto_requested_at",
        "auto_confirmed_at",
        "cycle_takeover_started_at",
    ):
        assert getattr(core, field) == 0.0
    assert not core.takeover_owner
    assert not core.manual_requested_by_ca
    assert not core.control_ever_owned
    assert not core.motion_ever_sent
    assert not core.motion_limit_reached
    assert not core.restore_auto_allowed
    assert core.original_mode == ""
    assert core.requested_mode == ""
    assert not core.mode_request_sent
    assert not core.mode_request_acknowledged
    assert core.blocked_reason == ""
    assert core.abort_reason == ""
    assert core.last_event == "RETURNED_TO_AUTO_MONITORING"
    status = core.status(ready(24.1))
    assert status["hazard_to_manual_request"] == 0.0
    assert status["manual_request_to_manual_confirm"] == 0.0
    assert status["total_takeover_duration"] == 0.0
    assert not status["actuator_path_ready"]
    assert not status["physical_ready"]


def test_62_two_cycles_have_new_hazard_and_takeover_timestamps():
    core = monitoring()
    first_hazard, first_takeover = _start_independent_cycle(core, 20.0)
    _complete_independent_cycle(core, 20.0)
    second_hazard, second_takeover = _start_independent_cycle(core, 40.0)
    assert core.cycle_id == 2
    assert second_hazard == 40.0
    assert second_hazard > first_hazard
    assert second_takeover == 40.5
    assert second_takeover > first_takeover
    completed = _complete_independent_cycle(core, 40.0)
    assert completed["cycle_id"] == 2
    assert completed["total_takeover_duration"] >= 0.0


def test_63_ten_cycles_are_independent_and_session_counts_are_cumulative():
    core = monitoring()
    starts = tuple(20.0 * index for index in range(1, 11))
    completed = []
    for expected_cycle, start in enumerate(starts, 1):
        _start_independent_cycle(core, start)
        completed.append(_complete_independent_cycle(core, start))
        assert core.cycle_id == expected_cycle
        assert core.completed_cycle_count == expected_cycle
        assert core.state == "AUTO_MISSION_MONITORING"
    assert [item["cycle_id"] for item in completed] == list(range(1, 11))
    assert all(item["total_takeover_duration"] >= 0.0 for item in completed)
    assert core.session_mode_request_count == 20


def test_64_second_cycle_fresh_hazard_is_not_limited_by_session_time():
    core = monitoring()
    _start_independent_cycle(core, 20.0)
    _complete_independent_cycle(core, 20.0)
    _, second_takeover = _start_independent_cycle(core, 40.0, "SLOW_DOWN")
    output = core.step(ready(
        42.9,
        fcu_mode="MANUAL",
        selected_command="SLOW_DOWN",
        mqtt_ack_received=True,
    ))
    assert output.state == "MOTION_ACTIVE"
    output = core.step(ready(
        second_takeover + 14.9,
        fcu_mode="MANUAL",
        selected_command="SLOW_DOWN",
        mqtt_ack_received=True,
    ))
    assert output.state == "MOTION_ACTIVE"
    output = core.step(ready(
        second_takeover + 15.0,
        fcu_mode="MANUAL",
        selected_command="SLOW_DOWN",
        mqtt_ack_received=True,
    ))
    assert output.state == "MOTION_ACTIVE"
    assert not output.abort_reason


def test_65_rc_baseline_and_motion_evidence_are_current_cycle_only():
    evidence = RcCycleEvidence(neutral_throttle_pwm=1500)
    baseline = [1500, 65535, 1500] + [65535] * 15
    motion = [1425, 65535, 1550] + [65535] * 15
    evidence.reset(1)
    assert evidence.capture_pre_motion(baseline)
    first = evidence.observe(
        motion,
        requested_throttle=10.0,
        requested_steering=15.0,
        motion_expected=True,
    )
    assert first["pre_motion_throttle_channel"] == 1500
    assert first["observed_throttle_pwm"] == 1550
    assert first["throttle_delta_from_pre_motion"] == 50
    assert first["steering_delta_from_pre_motion"] == -75
    assert first["rc_changed_from_pre_motion"]
    assert first["rc_matches_requested_command"]
    assert first["rc_command_delivered"]

    evidence.reset(2)
    assert evidence.status()["pre_motion_channels"] is None
    second_baseline = [1490, 65535, 1510] + [65535] * 15
    evidence.capture_pre_motion(second_baseline)
    assert evidence.status()["pre_motion_throttle_channel"] == 1510


def test_66_rc_neutral_and_release_are_recognized_without_overwriting_motion():
    evidence = RcCycleEvidence(neutral_throttle_pwm=1500)
    evidence.reset(1)
    evidence.capture_pre_motion([1500, 65535, 1500] + [65535] * 15)
    motion = [1425, 65535, 1550] + [65535] * 15
    evidence.observe(
        motion,
        requested_throttle=10.0,
        requested_steering=15.0,
        motion_expected=True,
    )
    evidence.observe(
        [1500, 65535, 1500] + [65535] * 15,
        requested_throttle=0.0,
        requested_steering=0.0,
        motion_expected=True,
    )
    final = evidence.observe(
        [0] * 18,
        requested_throttle=0.0,
        requested_steering=0.0,
        motion_expected=True,
    )
    assert final["neutral_observed"]
    assert final["release_observed"]
    assert final["observed_motion_channels"] == tuple(motion)


def test_67_rc_delivery_never_claims_physical_thruster_effectiveness():
    effective, status = classify_slow_effectiveness(10.0, 10.0)
    assert effective == "UNKNOWN"
    assert status == "PHYSICAL_EFFECT_UNKNOWN"
    effective, status = classify_slow_effectiveness(5.0, 10.0)
    assert effective == "NO"
    assert status == "SLOW_BELOW_EFFECTIVE_THRESHOLD"


def test_68_slow_throttle_is_derived_from_operator_cruise_reference():
    limits = SafetyLimits(
        maximum_throttle_percent=10.0,
        cruise_reference_throttle_percent=20.0,
        slow_factor=0.5,
        slow_throttle_percent=10.0,
        minimum_effective_throttle_percent=8.0,
        turn_throttle_percent=10.0,
    )
    assert limits.validate_first_test() == (True, "VALID")
    throttle, _, reason = command_to_test_output(
        "TURN_RIGHT_SLOW", 0.8, 0.2, limits
    )
    assert reason == "VALID"
    assert throttle == 10.0
    assert throttle > limits.minimum_effective_throttle_percent
    assert throttle < limits.cruise_reference_throttle_percent
    invalid = SafetyLimits(
        maximum_throttle_percent=10.0,
        cruise_reference_throttle_percent=30.0,
        slow_factor=0.5,
        slow_throttle_percent=10.0,
        minimum_effective_throttle_percent=8.0,
    )
    assert (
        invalid.validate_first_test()[1]
        == "SLOW_THROTTLE_BELOW_EFFECTIVE_THRESHOLD"
    )


def test_69_hud_and_launch_use_current_cycle_and_conservative_calibration_fields():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    status = {
        "session_id": "session-123",
        "cycle_id": 2,
        "cycle_elapsed_s": 1.5,
        "takeover_limit_s": 15.0,
        "state": "MOTION_ACTIVE",
        "requested_throttle": 10.0,
        "observed_throttle_pwm": 1550,
        "throttle_delta_from_pre_motion": 50,
        "rc_command_delivered": True,
        "slow_effective": "UNKNOWN",
        "physical_effect_status": "PHYSICAL_EFFECT_UNKNOWN",
    }
    rendered = render_auto_takeover_header(frame, status)
    assert rendered.shape == (480 + HEADER_HEIGHT, 640, 3)
    launch = LAUNCH.read_text()
    script = SCRIPT.read_text()
    manager = MANAGER.read_text()
    for name in (
        "neutral_throttle_pwm",
        "cruise_reference_throttle_percent",
        "slow_factor",
        "slow_throttle_percent",
        "minimum_effective_throttle_percent",
        "turn_throttle_percent",
        "maximum_test_throttle_percent",
    ):
        assert name in launch
        assert name in manager
    assert "CA_AUTO_CRUISE_REFERENCE_THROTTLE_PERCENT:-100.0" in script
    assert "CA_AUTO_SLOW_THROTTLE_PERCENT:-58.0" in script
    assert "CA_AUTO_MINIMUM_EFFECTIVE_THROTTLE_PERCENT:-58.0" in script
    assert "CA_AUTO_TURN_THROTTLE_PERCENT:-0.0" in script
    assert "CA_AUTO_MAX_TEST_THROTTLE_PERCENT" in script


def test_70_canonical_mapping_has_unambiguous_port_starboard_and_stop():
    limits = SafetyLimits(
        mapping_profile="SEAPORTAL_ACTUAL",
        maximum_throttle_percent=58.0,
        maximum_allowed_throttle_percent=58.0,
        cruise_reference_throttle_percent=100.0,
        slow_factor=0.58,
        slow_throttle_percent=58.0,
        minimum_effective_throttle_percent=58.0,
        turn_throttle_percent=0.0,
        maximum_steering_percent=100.0,
        maximum_allowed_steering_percent=100.0,
    )
    slow = canonical_thruster_mapping("SLOW_DOWN", limits)
    stop = canonical_thruster_mapping("STOP", limits)
    right = canonical_thruster_mapping("TURN_RIGHT", limits)
    right_slow = canonical_thruster_mapping("TURN_RIGHT_SLOW", limits)
    left = canonical_thruster_mapping("TURN_LEFT", limits)
    left_slow = canonical_thruster_mapping("TURN_LEFT_SLOW", limits)
    hold = canonical_thruster_mapping("HOLD_COURSE", limits)
    reverse = canonical_thruster_mapping(
        "TURN_RIGHT", limits, source_left=-0.2, source_right=-0.2
    )
    assert limits.validate_first_test() == (True, "VALID")
    assert (slow.throttle_percent, slow.steering_percent) == (58.0, 0.0)
    assert slow.throttle_percent < limits.cruise_reference_throttle_percent
    assert (stop.throttle_percent, stop.steering_percent) == (0.0, 0.0)
    assert stop.override_active
    assert (right.throttle_percent, right.steering_percent) == (0.0, -100.0)
    assert (
        right_slow.throttle_percent,
        right_slow.steering_percent,
    ) == (58.0, -100.0)
    assert (left.throttle_percent, left.steering_percent) == (0.0, 100.0)
    assert (
        left_slow.throttle_percent,
        left_slow.steering_percent,
    ) == (58.0, 100.0)
    assert not hold.override_active
    assert (hold.throttle_percent, hold.steering_percent) == (0.0, 0.0)
    assert AdapterCore(limits=limits, session_id="hold").update(
        "HOLD_COURSE", 0.0, 0.0, True, now=1.0
    ) == []
    assert not reverse.valid
    assert reverse.reason == "REVERSE_DETECTED"
    assert (reverse.throttle_percent, reverse.steering_percent) == (0.0, 0.0)
    assert (slow.requested_steering_pwm, slow.requested_throttle_pwm) == (
        1500,
        1790,
    )
    assert (right.requested_steering_pwm, right.requested_throttle_pwm) == (
        2000,
        1500,
    )
    assert (left.requested_steering_pwm, left.requested_throttle_pwm) == (
        1000,
        1500,
    )
    assert (stop.requested_steering_pwm, stop.requested_throttle_pwm) == (
        1500,
        1500,
    )
    assert max(
        slow.throttle_percent,
        right.throttle_percent,
        right_slow.throttle_percent,
        left.throttle_percent,
        left_slow.throttle_percent,
    ) == limits.maximum_throttle_percent
    too_high = SafetyLimits(
        maximum_throttle_percent=58.1,
        maximum_allowed_throttle_percent=58.0,
        cruise_reference_throttle_percent=100.0,
        slow_factor=0.58,
        slow_throttle_percent=58.0,
        minimum_effective_throttle_percent=58.0,
        turn_throttle_percent=0.0,
    )
    assert not too_high.validate_first_test()[0]


def test_71_motion_timer_starts_only_after_delivery_evidence():
    core = monitoring()
    core.step(ready(20.0, selected_command="SLOW_DOWN"))
    core.step(ready(20.5, selected_command="SLOW_DOWN"))
    core.consume_mode_request()
    core.report_mode_request("MANUAL", True)
    core.step(ready(20.6, fcu_mode="MANUAL", selected_command="SLOW_DOWN"))
    core.step(ready(20.7, fcu_mode="MANUAL", selected_command="SLOW_DOWN"))
    pending = core.step(
        ready(20.8, fcu_mode="MANUAL", selected_command="SLOW_DOWN")
    )
    assert pending.state == "MOTION_COMMAND_PENDING"
    assert core.motion_started_at == 0.0
    assert not core.motion_ever_sent
    assert not core.control_ever_owned
    active = core.step(ready(
        20.9,
        fcu_mode="MANUAL",
        selected_command="SLOW_DOWN",
        mqtt_ack_received=True,
    ))
    assert active.state == "MOTION_ACTIVE"
    assert core.motion_started_at == 20.9
    assert core.motion_ever_sent
    assert core.control_ever_owned


def test_72_failed_delivery_times_out_to_stop_without_motion_timer():
    core = monitoring()
    core.step(ready(20.0, selected_command="SLOW_DOWN"))
    core.step(ready(20.5, selected_command="SLOW_DOWN"))
    core.consume_mode_request()
    core.report_mode_request("MANUAL", True)
    core.step(ready(20.6, fcu_mode="MANUAL", selected_command="SLOW_DOWN"))
    core.step(ready(20.7, fcu_mode="MANUAL", selected_command="SLOW_DOWN"))
    core.step(ready(20.8, fcu_mode="MANUAL", selected_command="SLOW_DOWN"))
    output = core.step(
        ready(21.6, fcu_mode="MANUAL", selected_command="SLOW_DOWN")
    )
    assert output.state == "SAFE_NEUTRAL_WAIT_CLEAR"
    assert output.hardware_command == "STOP"
    assert output.command_publish_allowed
    assert output.blocked_reason == "MOTION_DELIVERY_TIMEOUT"
    assert core.motion_started_at == 0.0
    assert not core.motion_ever_sent


def test_73_hazard_return_during_clear_cancels_restore():
    core = manual_ready()
    core.step(ready(10.0, fcu_mode="MANUAL"))
    assert core.state == "CLEAR_HOLD"
    output = core.step(ready(
        10.5,
        fcu_mode="MANUAL",
        selected_command="TURN_LEFT",
    ))
    assert output.state == "AVOIDANCE_READY"
    assert core.clear_started_at == 0.0
    assert core.consume_mode_request() == ""
    pending = core.step(ready(
        10.6,
        fcu_mode="MANUAL",
        selected_command="TURN_LEFT",
    ))
    assert pending.state == "MOTION_COMMAND_PENDING"


def test_74_hazard_return_before_release_restarts_avoidance():
    core = manual_ready()
    core.step(ready(10.0, fcu_mode="MANUAL"))
    core.step(ready(12.6, fcu_mode="MANUAL"))
    output = core.step(ready(
        12.7,
        fcu_mode="MANUAL",
        selected_command="TURN_RIGHT",
        neutral_sent=True,
    ))
    assert output.state == "AVOIDANCE_READY"
    assert core.consume_mode_request() == ""


def test_75_manual_to_auto_before_release_is_operator_intervention():
    core = manual_ready()
    core.step(ready(10.0, fcu_mode="MANUAL"))
    core.step(ready(12.6, fcu_mode="MANUAL"))
    output = core.step(ready(12.7, fcu_mode="AUTO"))
    assert output.state == "ABORTED"
    assert output.abort_reason == "OPERATOR_MODE_INTERVENTION"


def test_76_neutral_confirmation_is_required_before_release():
    core = monitoring()
    core.step(ready(20.0, selected_command="SLOW_DOWN"))
    core.step(ready(20.5, selected_command="SLOW_DOWN"))
    core.consume_mode_request()
    core.report_mode_request("MANUAL", True)
    core.step(ready(20.6, fcu_mode="MANUAL", selected_command="SLOW_DOWN"))
    core.step(ready(20.7, fcu_mode="MANUAL"))
    core.step(ready(20.8, fcu_mode="MANUAL"))
    core.step(ready(23.4, fcu_mode="MANUAL"))
    output = core.step(ready(23.5, fcu_mode="MANUAL"))
    assert output.state == "NEUTRALIZING"
    assert core.consume_mode_request() == ""


def test_77_release_confirmation_wait_does_not_repeat_or_abort():
    core = manual_ready()
    core.step(ready(10.0, fcu_mode="MANUAL"))
    core.step(ready(12.6, fcu_mode="MANUAL"))
    core.step(ready(
        12.7,
        fcu_mode="MANUAL",
        neutral_sent=True,
        rc_neutral_confirmed=True,
    ))
    waiting = core.step(ready(
        20.0,
        fcu_mode="MANUAL",
        release_sent=True,
        release_echo_received=False,
    ))
    assert waiting.state == "RELEASING_CONTROL"
    assert waiting.blocked_reason == "WAIT_RELEASE_OWN_ECHO"
    assert not waiting.abort_reason
    assert core.consume_mode_request() == ""


def test_78_hazard_after_auto_confirmation_starts_new_cycle():
    core = manual_ready()
    _finish_clear_release_auto(core, clear_at=10.0, release_at=12.6)
    assert core.cycle_id == 1
    core.step(ready(20.0, selected_command="STOP"))
    output = core.step(ready(20.5, selected_command="STOP"))
    assert output.state == "TAKEOVER_REQUESTED"
    assert core.cycle_id == 2


def test_79_twenty_cycle_records_have_independent_delivery_and_nonnegative_times():
    core = monitoring()
    records = []
    for index in range(20):
        start = 20.0 + index * 20.0
        _start_independent_cycle(core, start, "TURN_LEFT_SLOW")
        records.append(_complete_independent_cycle(core, start))
    assert core.completed_cycle_count == 20
    assert [record["cycle_id"] for record in records] == list(range(1, 21))
    assert all(
        record["motion_delivery_evidence"] == "MQTT_ACK_RECEIVED"
        for record in records
    )
    timestamp_fields = (
        "first_hazard_time",
        "manual_request_time",
        "manual_confirmed_time",
        "motion_pending_time",
        "motion_start_time",
        "clear_start_time",
        "release_start_time",
        "auto_request_time",
        "auto_confirmed_time",
    )
    assert all(
        all(record[field] >= 0.0 for field in timestamp_fields)
        and record["total_takeover_duration"] >= 0.0
        for record in records
    )
    assert len({record["first_hazard_time"] for record in records}) == 20


def test_80_hud_exposes_delivery_watchdog_release_and_unverified_physical_effect():
    status = {
        "session_id": "fake",
        "cycle_id": 10,
        "completed_cycle_count": 9,
        "state": "MOTION_ACTIVE",
        "fcu_mode": "MANUAL",
        "fcu_armed": True,
        "desired_command": "SLOW_DOWN",
        "mapped_command": "SLOW_DOWN",
        "command_published": True,
        "mqtt_ack_received": True,
        "mqtt_own_echo_received": True,
        "rc_command_delivered": True,
        "requested_throttle": 58.0,
        "requested_steering": 0.0,
        "requested_steering_pwm": 1500,
        "requested_throttle_pwm": 1790,
        "observed_steering_pwm": 1500,
        "observed_throttle_pwm": 1790,
        "motion_watchdog_age_s": 0.1,
        "command_freshness_watchdog_s": 2.0,
        "clear_elapsed_s": 0.0,
    }
    text = "\n".join(header_lines(status, 1600))
    assert "CYCLE_ID:10" in text
    assert "COMPLETED_CYCLES:9" in text
    assert "PUBLISHED:Y" in text
    assert "MQTT ACK:Y" in text and "OWN ECHO:Y" in text
    assert "REQ PWM CH1:1500 CH3:1790" in text
    assert "WATCHDOG:0.1/2.0s" in text
    assert "SLOW COMMAND DELIVERED:Y" in text
    assert "SLOW PHYSICAL EFFECT:UNVERIFIED" in text
    assert "PHYSICAL EFFECT CONFIRMED" not in text


def test_81_dry_check_rejects_slow_below_effective_threshold():
    env = dict(
        os.environ,
        CA_AUTO_CRUISE_REFERENCE_THROTTLE_PERCENT="30",
        CA_AUTO_SLOW_FACTOR="0.5",
        CA_AUTO_MINIMUM_EFFECTIVE_THROTTLE_PERCENT="8",
        CA_AUTO_SLOW_THROTTLE_PERCENT="10",
        CA_AUTO_MAX_TEST_THROTTLE_PERCENT="10",
    )
    result = subprocess.run(
        [str(SCRIPT), "--dry-check"],
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "SLOW_THROTTLE_BELOW_EFFECTIVE_THRESHOLD" in result.stderr


def test_82_adapter_can_reacquire_control_after_bounded_post_release_flush():
    limits = SafetyLimits(
        mapping_profile="SEAPORTAL_ACTUAL",
        maximum_throttle_percent=58.0,
        maximum_allowed_throttle_percent=58.0,
        cruise_reference_throttle_percent=100.0,
        slow_factor=0.58,
        slow_throttle_percent=58.0,
        minimum_effective_throttle_percent=58.0,
        turn_throttle_percent=0.0,
        maximum_steering_percent=100.0,
        maximum_allowed_steering_percent=100.0,
    )
    adapter = AdapterCore(limits=limits, session_id="repeat")
    for cycle in range(10):
        motion = adapter.update(
            "TURN_RIGHT_SLOW", 0.8, 0.2, True, now=cycle + 1.0
        )
        assert [action.kind for action in motion] == ["MOTION"]
        assert motion[0].payload["throttle"] == 58.0
        assert motion[0].payload["steering"] == -100.0
        assert not {
            "pwm", "channels", "channel_steering", "channel_throttle"
        } & motion[0].payload.keys()
        released = adapter.update(
            "HOLD_COURSE", 0.0, 0.0, True, now=cycle + 1.1
        )
        assert [action.kind for action in released] == ["NEUTRAL", "RELEASE"]
        assert released[0].payload["throttle"] == 0.0
        assert released[0].payload["steering"] == 0.0
        assert released[1].payload["release"] is True
        flush = adapter.update(
            "HOLD_COURSE", 0.0, 0.0, False, now=cycle + 1.2
        )
        assert flush == []
        assert not adapter.aborted
        assert not adapter.control_acquired


def test_83_adapter_fault_is_fail_closed_before_motion():
    core = monitoring()
    core.step(ready(20.0, selected_command="SLOW_DOWN"))
    core.step(ready(20.5, selected_command="SLOW_DOWN"))
    core.consume_mode_request()
    core.report_mode_request("MANUAL", True)
    core.step(ready(20.6, fcu_mode="MANUAL", selected_command="SLOW_DOWN"))
    output = core.step(ready(
        20.7,
        fcu_mode="MANUAL",
        selected_command="SLOW_DOWN",
        adapter_fault_reason="MQTT_PUBLISH_FAILED:FAKE",
    ))
    assert output.state == "AVOIDANCE_READY"
    output = core.step(ready(
        20.8,
        fcu_mode="MANUAL",
        selected_command="SLOW_DOWN",
        adapter_fault_reason="MQTT_PUBLISH_FAILED:FAKE",
    ))
    assert output.state == "ABORTED"
    assert output.abort_reason == "MQTT_PUBLISH_FAILED:FAKE"
    assert not output.motion_allowed


def test_84_external_thruster_source_matches_read_only_audit_hash():
    external_source = Path(
        "/home/seano/Seano_ws/src/seano_command/"
        "seano_command/thruster_node.py"
    )
    assert external_source.is_file()
    digest = hashlib.sha256(external_source.read_bytes()).hexdigest()
    assert (
        digest
        == "9d1ca1dd210f886a9cc5f2b3300a7edd"
        "3f1699cf66f0baeb80b58b6c09567c96"
    )


def test_85_rc_evidence_uses_runtime_channel_parameters_for_seaportal_values():
    evidence = RcCycleEvidence(
        steering_channel_index=0,
        throttle_channel_index=2,
        pwm_min=1000,
        neutral_throttle_pwm=1500,
        pwm_max=2000,
    )
    cases = (
        (58.0, 0.0, 1500, 1790),
        (0.0, -100.0, 2000, 1500),
        (0.0, 100.0, 1000, 1500),
        (58.0, -100.0, 2000, 1790),
        (58.0, 100.0, 1000, 1790),
        (0.0, 0.0, 1500, 1500),
    )
    for cycle, (throttle, steering, ch1, ch3) in enumerate(cases, 1):
        evidence.reset(cycle)
        evidence.capture_pre_motion(
            [1500, 65535, 1500] + [65535] * 15
        )
        channels = [ch1, 65535, ch3] + [65535] * 15
        observed = evidence.observe(
            channels,
            requested_throttle=throttle,
            requested_steering=steering,
            motion_expected=True,
        )
        assert observed["current_rc_matches_requested_command"]
        assert observed["rc_command_delivered"]
        assert observed["observed_steering_pwm"] == ch1
        assert observed["observed_throttle_pwm"] == ch3


def _failsafe_stop_active(**fault):
    core = monitoring()
    fault_values = dict(
        selected_command="STOP",
        safe_command="STOP",
        desired_command="STOP",
        failsafe_active=True,
    )
    fault_values.update(fault)
    requested = core.step(ready(20.0, **fault_values))
    assert requested.state == "TAKEOVER_REQUESTED"
    assert requested.hardware_command == "STOP"
    assert requested.requested_mode == "MANUAL"
    assert core.consume_mode_request() == "MANUAL"
    core.report_mode_request("MANUAL", True)
    waiting = core.step(ready(20.1, **fault_values))
    assert waiting.state == "WAITING_FOR_MANUAL_CONFIRMATION"
    confirmed = core.step(
        ready(20.2, fcu_mode="MANUAL", **fault_values)
    )
    assert confirmed.state == "AVOIDANCE_READY"
    pending = core.step(
        ready(20.3, fcu_mode="MANUAL", **fault_values)
    )
    assert pending.state == "MOTION_COMMAND_PENDING"
    assert pending.hardware_command == "STOP"
    assert pending.command_publish_allowed
    active = core.step(
        ready(
            20.4,
            fcu_mode="MANUAL",
            neutral_sent=True,
            adapter_control_acquired=True,
            rc_command_delivered=True,
            **fault_values,
        )
    )
    assert active.state == "STOP_ACTIVE"
    assert active.hardware_command == "STOP"
    return core, fault_values


def test_86_armed_auto_healthy_hold_remains_unowned_normal_mission():
    core = monitoring()
    output = core.step(ready(20.0))
    status = core.status(ready(20.0))
    assert output.state == "AUTO_MISSION_MONITORING"
    assert not core.takeover_owner
    assert core.consume_mode_request() == ""
    assert status["operational_reason"] == "NORMAL_NO_OBSTACLE"


def test_87_armed_auto_lost_perception_requests_manual_stop():
    core = monitoring()
    data = ready(
        20.0,
        perception_valid=False,
        perception_state="LOST_PERCEPTION",
        camera_perception_available=False,
        failsafe_active=True,
        selected_command="STOP",
        safe_command="STOP",
        desired_command="STOP",
    )
    output = core.step(data)
    assert output.state == "TAKEOVER_REQUESTED"
    assert output.hardware_command == "STOP"
    assert output.requested_mode == "MANUAL"
    assert core.takeover_owner
    assert core.status(data)["operational_reason"] == (
        "LOST_PERCEPTION_STOP_TAKEOVER"
    )


def test_88_failsafe_active_is_not_mapped_to_hold_course():
    core = monitoring()
    data = ready(
        20.0,
        failsafe_active=True,
        selected_command="STOP",
        safe_command="STOP",
        desired_command="STOP",
    )
    output = core.step(data)
    assert output.hardware_command == "STOP"
    assert output.hardware_command != "HOLD_COURSE"
    assert core.status(data)["operational_reason"] == (
        "FAILSAFE_STOP_TAKEOVER"
    )


def test_89_manager_stale_requests_stop_takeover():
    core = monitoring()
    output = core.step(ready(
        20.0,
        manager_fresh=False,
        perception_valid=False,
        camera_perception_available=False,
        selected_command="STOP",
        safe_command="STOP",
        desired_command="STOP",
    ))
    assert output.state == "TAKEOVER_REQUESTED"
    assert output.hardware_command == "STOP"
    assert core.failsafe_stop_reason == "MANAGER_STALE"


def test_90_fault_stop_remains_neutral_and_owned_while_fault_active():
    core, fault = _failsafe_stop_active()
    for now in (21.0, 22.0, 30.0):
        output = core.step(ready(
            now,
            fcu_mode="MANUAL",
            neutral_sent=True,
            adapter_control_acquired=True,
            **fault,
        ))
        assert output.state == "STOP_ACTIVE"
        assert output.hardware_command == "STOP"
        assert output.command_publish_allowed
        assert not output.motion_allowed
        assert core.takeover_owner
        assert core.consume_mode_request() == ""


def test_91_auto_restore_waits_for_recovery_fresh_hold_and_clear_hold():
    core, fault = _failsafe_stop_active()
    still_fault = core.step(ready(
        21.0,
        fcu_mode="MANUAL",
        neutral_sent=True,
        adapter_control_acquired=True,
        **fault,
    ))
    assert still_fault.state == "STOP_ACTIVE"
    recovered = ready(
        21.1,
        fcu_mode="MANUAL",
        neutral_sent=True,
        adapter_control_acquired=True,
    )
    clear = core.step(recovered)
    assert clear.state == "CLEAR_HOLD"
    assert clear.hardware_command == "STOP"
    assert core.status(recovered)["operational_reason"] == (
        "WAITING_FOR_PERCEPTION_RECOVERY"
    )
    assert core.consume_mode_request() == ""
    before_hold = core.step(ready(
        23.5,
        fcu_mode="MANUAL",
        neutral_sent=True,
        adapter_control_acquired=True,
    ))
    assert before_hold.state == "CLEAR_HOLD"
    assert core.consume_mode_request() == ""
    releasing = core.step(ready(
        23.7,
        fcu_mode="MANUAL",
        neutral_sent=True,
        adapter_control_acquired=True,
    ))
    assert releasing.state == "NEUTRALIZING"
    releasing = core.step(ready(
        23.8,
        fcu_mode="MANUAL",
        neutral_sent=True,
        rc_neutral_confirmed=True,
        adapter_control_acquired=True,
    ))
    assert releasing.state == "RELEASING_CONTROL"
    assert core.consume_mode_request() == ""
    requested = core.step(ready(
        23.9,
        fcu_mode="MANUAL",
        neutral_sent=True,
        release_sent=True,
        release_echo_received=True,
    ))
    assert requested.state == "AUTO_RESTORE_REQUESTED"
    assert core.consume_mode_request() == "AUTO"


def test_92_fault_return_during_clear_hold_reasserts_stop():
    core, _ = _failsafe_stop_active()
    core.step(ready(
        21.0,
        fcu_mode="MANUAL",
        neutral_sent=True,
        adapter_control_acquired=True,
    ))
    output = core.step(ready(
        22.0,
        fcu_mode="MANUAL",
        failsafe_active=True,
        selected_command="STOP",
        safe_command="STOP",
        desired_command="STOP",
        neutral_sent=True,
        adapter_control_acquired=True,
    ))
    assert output.state == "STOP_ACTIVE"
    assert output.hardware_command == "STOP"
    assert core.consume_mode_request() == ""


def test_93_hud_exposes_distinct_normal_fault_and_recovery_reasons():
    for reason in (
        "NORMAL_NO_OBSTACLE",
        "FAILSAFE_STOP_TAKEOVER",
        "LOST_PERCEPTION_STOP_TAKEOVER",
        "WAITING_FOR_PERCEPTION_RECOVERY",
    ):
        text = "\n".join(
            header_lines({"operational_reason": reason}, 1600)
        )
        assert f"REASON:{reason}" in text


def test_94_command_and_watchdog_stale_each_request_stop_takeover():
    for stale in (
        {"command_fresh": False},
        {"watchdog_fresh": False},
    ):
        core = monitoring()
        output = core.step(ready(
            20.0,
            selected_command="STOP",
            safe_command="STOP",
            desired_command="STOP",
            **stale,
        ))
        assert output.state == "TAKEOVER_REQUESTED"
        assert output.hardware_command == "STOP"
        assert output.requested_mode == "MANUAL"


def test_95_armed_auto_startup_fault_does_not_wait_without_takeover():
    core = AutoTakeoverCore(started_at=0.0)
    output = core.step(ready(
        8.0,
        perception_valid=False,
        perception_state="LOST_PERCEPTION",
        camera_perception_available=False,
        failsafe_active=True,
        selected_command="STOP",
        safe_command="STOP",
        desired_command="STOP",
    ))
    assert output.state == "TAKEOVER_REQUESTED"
    assert output.hardware_command == "STOP"
    assert core.consume_mode_request() == "MANUAL"


def test_96_fault_takeover_cannot_confirm_auto_before_clear_hold():
    core, _ = _failsafe_stop_active()
    core.step(ready(
        21.0,
        fcu_mode="MANUAL",
        neutral_sent=True,
        adapter_control_acquired=True,
    ))
    output = core.step(ready(
        21.1,
        fcu_mode="AUTO",
        neutral_sent=True,
        adapter_control_acquired=True,
    ))
    assert output.state != "AUTO_CONFIRMED"
    assert core.completed_cycle_count == 0


def test_97_fault_stop_waits_for_neutral_rc_delivery_confirmation():
    core = monitoring()
    fault = dict(
        selected_command="STOP",
        safe_command="STOP",
        desired_command="STOP",
        failsafe_active=True,
    )
    core.step(ready(20.0, **fault))
    core.consume_mode_request()
    core.report_mode_request("MANUAL", True)
    core.step(ready(20.1, **fault))
    core.step(ready(20.2, fcu_mode="MANUAL", **fault))
    core.step(ready(20.3, fcu_mode="MANUAL", **fault))
    pending = core.step(ready(
        20.4,
        fcu_mode="MANUAL",
        neutral_sent=True,
        adapter_control_acquired=True,
        rc_command_delivered=False,
        **fault,
    ))
    assert pending.state == "MOTION_COMMAND_PENDING"
    assert pending.blocked_reason == "WAIT_STOP_RC_DELIVERY"
    delivered = core.step(ready(
        20.5,
        fcu_mode="MANUAL",
        neutral_sent=True,
        adapter_control_acquired=True,
        rc_command_delivered=True,
        **fault,
    ))
    assert delivered.state == "STOP_ACTIVE"


def test_98_auto_failsafe_stop_holds_neutral_without_release():
    limits = SafetyLimits(
        mapping_profile="SEAPORTAL_ACTUAL",
        maximum_throttle_percent=58.0,
        maximum_allowed_throttle_percent=58.0,
        cruise_reference_throttle_percent=100.0,
        slow_factor=0.58,
        slow_throttle_percent=58.0,
        minimum_effective_throttle_percent=58.0,
        turn_throttle_percent=0.0,
        maximum_steering_percent=100.0,
        maximum_allowed_steering_percent=100.0,
    )
    adapter = AdapterCore(
        limits=limits,
        session_id="failsafe-stop",
        bounded_stop_neutral=True,
    )
    motion = adapter.update(
        "TURN_RIGHT_SLOW", 0.8, 0.2, True, now=1.0
    )
    assert [action.kind for action in motion] == ["MOTION"]
    stop = adapter.hold_failsafe_stop(now=1.1)
    assert stop
    assert all(action.kind == "NEUTRAL" for action in stop)
    assert all(action.payload["throttle"] == 0.0 for action in stop)
    assert all(action.payload["steering"] == 0.0 for action in stop)
    assert not any(action.kind == "RELEASE" for action in stop)
    assert adapter.held
    assert adapter.control_acquired
    assert not adapter.aborted
    assert adapter.hold_failsafe_stop(now=1.2) == []
    assert adapter.held


def test_99_failsafe_stop_hold_is_isolated_to_auto_runtime():
    auto_launch = LAUNCH.read_text()
    phase_launch = (
        PACKAGE_ROOT / "launch" / "phase7_cuav_usb_hardware.launch.py"
    ).read_text()
    adapter_node = (
        PACKAGE_ROOT
        / "seano_vision"
        / "guarded_thruster_test_adapter_node.py"
    ).read_text()
    assert '"hardware_test_hold_stop_on_failsafe": "true"' in auto_launch
    assert (
        '"hardware_test_hold_stop_on_failsafe",\n'
        '            default_value="false"'
    ) in phase_launch
    assert '("hold_stop_on_failsafe", False)' in adapter_node
    assert "hold_stop_on_failsafe" not in MANUAL.read_text()


def _prepare_auto_restore():
    core = manual_ready()
    core.step(ready(10.0, fcu_mode="MANUAL"))
    assert core.step(
        ready(12.6, fcu_mode="MANUAL")
    ).state == "NEUTRALIZING"
    assert core.step(ready(
        12.7,
        fcu_mode="MANUAL",
        neutral_sent=True,
        rc_neutral_confirmed=True,
    )).state == "RELEASING_CONTROL"
    requested = core.step(ready(
        12.8,
        fcu_mode="MANUAL",
        neutral_sent=True,
        rc_neutral_confirmed=True,
        release_sent=True,
        release_echo_received=True,
    ))
    assert requested.state == "AUTO_RESTORE_REQUESTED"
    assert core.consume_mode_request() == "AUTO"
    return core


def test_100_first_auto_request_fails_second_succeeds():
    core = _prepare_auto_restore()
    core.report_mode_request("AUTO", False)
    assert core.state == "AUTO_RESTORE_RETRY"
    retried = core.step(ready(13.9, fcu_mode="MANUAL"))
    assert retried.state == "AUTO_RESTORE_REQUESTED"
    assert core.consume_mode_request() == "AUTO"
    assert core.mode_request_count == 2
    core.report_mode_request("AUTO", True)
    assert core.step(
        ready(14.0, fcu_mode="MANUAL")
    ).state == "WAITING_FOR_AUTO_CONFIRMATION"
    assert core.step(
        ready(14.1, fcu_mode="AUTO")
    ).state == "AUTO_REJOIN_VERIFY"
    assert core.step(
        ready(14.7, fcu_mode="AUTO")
    ).state == "AUTO_CONFIRMED"


def test_101_service_success_without_auto_mode_keeps_waiting():
    core = _prepare_auto_restore()
    core.report_mode_request("AUTO", True)
    output = core.step(ready(13.0, fcu_mode="MANUAL"))
    assert output.state == "WAITING_FOR_AUTO_CONFIRMATION"
    assert core.auto_service_response == "ACCEPTED"
    assert core.auto_restore_pending
    assert not core.auto_mode_observed


def test_102_auto_mode_before_service_response_starts_rejoin():
    core = _prepare_auto_restore()
    output = core.step(ready(12.9, fcu_mode="AUTO"))
    assert output.state == "AUTO_REJOIN_VERIFY"
    assert core.auto_mode_observed
    assert core.auto_service_response == "PENDING"
    assert not core.abort_reason


def test_103_operator_auto_while_waiting_is_restore_confirmation():
    core = _prepare_auto_restore()
    core.report_mode_request("AUTO", True)
    core.step(ready(12.9, fcu_mode="MANUAL"))
    output = core.step(ready(13.0, fcu_mode="AUTO"))
    assert output.state == "AUTO_REJOIN_VERIFY"
    assert not output.abort_reason


def test_104_hazard_after_neutral_before_release_resumes_same_cycle():
    core = manual_ready()
    core.step(ready(10.0, fcu_mode="MANUAL"))
    core.step(ready(12.6, fcu_mode="MANUAL"))
    core.step(ready(
        12.7,
        fcu_mode="MANUAL",
        neutral_sent=True,
        rc_neutral_confirmed=True,
    ))
    cycle_id = core.cycle_id
    output = core.step(ready(
        12.8,
        fcu_mode="MANUAL",
        selected_command="TURN_LEFT",
    ))
    assert output.state == "AVOIDANCE_READY"
    assert core.cycle_id == cycle_id
    assert core.consume_mode_request() == ""


def test_105_hazard_during_auto_retry_resumes_without_manual_request():
    core = _prepare_auto_restore()
    core.report_mode_request("AUTO", False)
    cycle_id = core.cycle_id
    output = core.step(ready(
        13.0,
        fcu_mode="MANUAL",
        selected_command="TURN_RIGHT_SLOW",
    ))
    assert output.state == "AVOIDANCE_READY"
    assert core.cycle_id == cycle_id
    assert core.consume_mode_request() == ""
    events = {event["event"] for event in core.consume_events()}
    assert "HAZARD_RETURNED_DURING_RESTORE" in events


def test_106_auto_restore_timeout_is_recoverable_and_rate_limited():
    core = _prepare_auto_restore()
    for now in (13.0, 14.0, 15.7):
        output = core.step(ready(now, fcu_mode="MANUAL"))
        assert output.state in {
            "AUTO_RESTORE_REQUESTED",
            "AUTO_RESTORE_RETRY",
            "WAITING_FOR_AUTO_CONFIRMATION",
        }
        assert not output.abort_reason
    output = core.step(ready(15.9, fcu_mode="MANUAL"))
    assert output.state == "AUTO_RESTORE_RETRY"
    output = core.step(ready(16.0, fcu_mode="MANUAL"))
    assert output.state == "AUTO_RESTORE_REQUESTED"
    assert core.consume_mode_request() == "AUTO"
    assert core.consume_mode_request() == ""


def test_107_restore_path_real_faults_still_abort():
    for overrides, reason in (
        ({"fcu_connected": False}, "FCU_DISCONNECTED"),
        ({"mqtt_connected": False}, "MQTT_DISCONNECTED"),
        ({"rc_publisher_name": "/other"}, "RC_PATH_CHANGED"),
        ({"foreign_active": True}, "FOREIGN_ACTIVE_COMMAND"),
    ):
        core = _prepare_auto_restore()
        output = core.step(ready(
            13.0,
            fcu_mode="MANUAL",
            **overrides,
        ))
        assert output.state == "ABORTED"
        assert output.abort_reason == reason


def test_108_auto_rejoin_resets_cycle_only_after_verified_mode():
    core = _prepare_auto_restore()
    old_cycle = core.cycle_id
    core.report_mode_request("AUTO", True)
    core.step(ready(13.0, fcu_mode="MANUAL"))
    core.step(ready(13.1, fcu_mode="AUTO"))
    assert core.takeover_owner
    assert core.original_mode == "AUTO"
    assert core.cycle_id == old_cycle
    core.step(ready(13.7, fcu_mode="AUTO"))
    assert core.state == "AUTO_CONFIRMED"
    assert not core.takeover_owner
    output = core.step(ready(13.8, fcu_mode="AUTO"))
    assert output.state == "AUTO_MISSION_MONITORING"
    assert core.cycle_id == old_cycle
    assert core.original_mode == ""
    assert not core.manual_requested_by_ca
    assert core.completed_cycle_count == 1


def test_109_mission_complete_stops_future_takeovers():
    core = monitoring()
    output = core.step(ready(
        20.0,
        mission_status_known=True,
        mission_active=False,
    ))
    assert output.state == "MISSION_COMPLETE"
    for now in (21.0, 30.0):
        output = core.step(ready(
            now,
            selected_command="STOP",
            mission_status_known=True,
            mission_active=False,
        ))
        assert output.state == "MISSION_COMPLETE"
        assert not core.takeover_owner
        assert core.consume_mode_request() == ""


def test_110_auto_adapter_uses_exactly_one_neutral_and_release():
    limits = SafetyLimits(
        mapping_profile="SEAPORTAL_ACTUAL",
        maximum_throttle_percent=58.0,
        maximum_allowed_throttle_percent=58.0,
        cruise_reference_throttle_percent=100.0,
        slow_factor=0.58,
        slow_throttle_percent=58.0,
        minimum_effective_throttle_percent=58.0,
        turn_throttle_percent=0.0,
        maximum_steering_percent=100.0,
        maximum_allowed_steering_percent=100.0,
    )
    adapter = AdapterCore(
        limits=limits,
        neutral_repetitions=1,
        release_repetitions=1,
        bounded_stop_neutral=True,
        release_without_extra_neutral=True,
    )
    adapter.update("SLOW_DOWN", 0.5, 0.5, True, now=1.0)
    neutral = adapter.update("STOP", 0.0, 0.0, True, now=2.0)
    release = adapter.update(
        "HOLD_COURSE", 0.0, 0.0, True, now=3.0
    )
    assert [action.kind for action in neutral] == ["NEUTRAL"]
    assert [action.kind for action in release] == ["RELEASE"]


def test_111_three_failed_auto_requests_enter_safe_manual_wait():
    core = _prepare_auto_restore()
    for request_number, now in ((1, 13.9), (2, 15.0)):
        core.report_mode_request("AUTO", False)
        core.step(ready(now, fcu_mode="MANUAL"))
        assert core.consume_mode_request() == "AUTO"
        assert core.mode_request_count == request_number + 1
    core.report_mode_request("AUTO", False)
    output = core.step(ready(16.1, fcu_mode="MANUAL"))
    assert output.state == "SAFE_MANUAL_WAIT_AUTO"
    assert output.blocked_reason == "AUTO_RESTORE_PENDING"
    assert not output.abort_reason
    assert output.hardware_command == "STOP"
    assert not output.command_publish_allowed


def test_112_mode_service_unavailable_remains_hard_abort():
    core = _prepare_auto_restore()
    core.report_mode_service_unavailable("AUTO")
    assert core.state == "ABORTED"
    assert core.abort_reason == "AUTO_MODE_SERVICE_UNAVAILABLE"


def test_113_mission_completion_after_rejoin_is_terminal():
    core = _prepare_auto_restore()
    core.report_mode_request("AUTO", True)
    core.step(ready(13.0, fcu_mode="MANUAL"))
    core.step(ready(13.1, fcu_mode="AUTO"))
    core.step(ready(13.7, fcu_mode="AUTO"))
    output = core.step(ready(
        13.8,
        fcu_mode="AUTO",
        mission_status_known=True,
        mission_active=False,
    ))
    assert output.state == "MISSION_COMPLETE"
    assert not core.takeover_owner
    events = {event["event"] for event in core.consume_events()}
    assert "MISSION_COMPLETE" in events


def test_114_hud_contains_required_auto_restore_fields():
    status = {
        "state": "AUTO_RESTORE_RETRY",
        "cycle_id": 4,
        "completed_cycle_count": 3,
        "fcu_mode": "MANUAL",
        "original_mode": "AUTO",
        "takeover_owner": True,
        "neutral_sent": True,
        "release_sent": True,
        "auto_request_count": 2,
        "auto_service_response": "REJECTED",
        "auto_mode_observed": False,
        "auto_restore_pending": True,
        "auto_rejoin_verified": False,
        "mission_active": True,
        "blocked_reason": "AUTO_RESTORE_PENDING",
        "abort_reason": "",
    }
    text = "\n".join(header_lines(status, 1600))
    for value in (
        "STATE:AUTO_RESTORE_RETRY",
        "CYCLE_ID:4",
        "COMPLETED_CYCLES:3",
        "FCU MODE:MANUAL",
        "ORIGINAL MODE:AUTO",
        "OWNER:Y",
        "NEUTRAL SENT:Y",
        "RELEASE SENT:Y",
        "AUTO REQUEST COUNT:2",
        "AUTO SERVICE RESPONSE:REJECTED",
        "AUTO MODE OBSERVED:N",
        "AUTO RESTORE PENDING:Y",
        "AUTO REJOIN VERIFIED:N",
        "MISSION ACTIVE:Y",
        "BLOCKED REASON:AUTO_RESTORE_PENDING",
        "ABORT REASON:-",
    ):
        assert value in text


def test_115_manager_logs_restore_response_and_reads_mission_status():
    manager = MANAGER.read_text()
    assert '"AUTO_RESTORE_SERVICE_RESPONSE"' in manager
    assert 'request.custom_mode = mode' in manager
    assert '"/mavros/mission/waypoints"' in manager
    assert '"/mavros/mission/reached"' in manager
    assert '"/ca/hardware_test/release_own_echo_received"' in manager
