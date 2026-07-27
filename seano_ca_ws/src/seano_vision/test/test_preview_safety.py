import unittest
from pathlib import Path

from seano_vision.risk_policy import normalize_command_details
from seano_vision.thruster_preview import (
    command_to_left_right, evaluate_actuator_path_ready, normalized_to_preview,
    actuator_path_gate_open, select_pool_turn_away_command, takeover_request_allowed,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
PREVIEW_NODE = PACKAGE_ROOT / "seano_vision" / "thruster_adapter_preview_node.py"
MODE_MANAGER = PACKAGE_ROOT / "seano_vision" / "mission_mode_manager_node.py"
AUTO_MANAGER = PACKAGE_ROOT / "seano_vision" / "auto_controller_stub_node.py"
POOL_SCRIPT = REPO_ROOT / "seano_ca_ws" / "run_pool_existing_control_path.sh"
PHASE7_LAUNCH = PACKAGE_ROOT / "launch" / "phase7_cuav_usb_hardware.launch.py"


def lr(command):
    return command_to_left_right(command)[:2]


def ready(**overrides):
    values = dict(enabled=True, left_fresh=True, right_fresh=True, command_fresh=True,
                  failsafe_active=False, dry_run=False, external_interface_confirmed=True,
                  external_arbitration_confirmed=True, hardware_output_enabled=True)
    values.update(overrides)
    return evaluate_actuator_path_ready(**values)[0]


def pool(x, risk=.7, close=False):
    return select_pool_turn_away_command(risk=risk, x_ratio=x, center_band_ratio=.35,
        slow_threshold=.3, turn_threshold=.6, stop_threshold=.92, very_close=close)


class PreviewSafetyTests(unittest.TestCase):
    def test_01_hold_recognized(self): self.assertEqual(normalize_command_details(" HOLD_COURSE ")[:2], ("HOLD_COURSE", True))
    def test_02_stop_zero(self): self.assertEqual(lr("STOP"), (0.0, 0.0))
    def test_03_slow_both_forward(self): self.assertGreater(min(lr("SLOW_DOWN")), 0.0)
    def test_04_slow_equal(self): self.assertAlmostEqual(*lr("SLOW_DOWN"))
    def test_05_left_slow_right_greater(self): self.assertGreater(lr("TURN_LEFT_SLOW")[1], lr("TURN_LEFT_SLOW")[0])
    def test_06_right_slow_left_greater(self): self.assertGreater(lr("TURN_RIGHT_SLOW")[0], lr("TURN_RIGHT_SLOW")[1])
    def test_07_left_right_greater(self): self.assertGreater(lr("TURN_LEFT")[1], lr("TURN_LEFT")[0])
    def test_08_right_left_greater(self): self.assertGreater(lr("TURN_RIGHT")[0], lr("TURN_RIGHT")[1])
    def test_09_space_normalization(self): self.assertEqual(normalize_command_details("turn left slow")[0], "TURN_LEFT_SLOW")
    def test_10_alias_normalization(self): self.assertEqual(normalize_command_details("LEFT_SLOW")[0], "TURN_LEFT_SLOW")
    def test_11_unknown_fails_stop(self): self.assertEqual(normalize_command_details("warp")[:2], ("STOP", False))
    def test_12_starboard_turns_port(self): self.assertEqual(pool(.9).command, "TURN_LEFT")
    def test_13_port_turns_starboard(self): self.assertEqual(pool(.1).command, "TURN_RIGHT")
    def test_14_center_close_stops(self): self.assertEqual(pool(.5, risk=.4, close=True).command, "STOP")
    def test_15_slow_preview(self):
        p = normalized_to_preview(*lr("SLOW_DOWN")); self.assertAlmostEqual(p["throttle"], 16.5); self.assertEqual(p["steering"], 0)
    def test_16_left_slow_preview(self):
        p = normalized_to_preview(*lr("TURN_LEFT_SLOW")); self.assertAlmostEqual(p["throttle"], 24.5); self.assertAlmostEqual(p["steering"], -24.5)
    def test_17_right_slow_preview(self):
        p = normalized_to_preview(*lr("TURN_RIGHT_SLOW")); self.assertAlmostEqual(p["throttle"], 24.5); self.assertAlmostEqual(p["steering"], 24.5)
    def test_18_stop_preview(self):
        p = normalized_to_preview(*lr("STOP")); self.assertEqual((p["throttle"], p["steering"]), (0.0, 0.0))
    def test_19_slow_pwm(self):
        p = normalized_to_preview(*lr("SLOW_DOWN")); self.assertEqual(p["pwm_ch1"], 1500); self.assertIn(p["pwm_ch3"], (1582, 1583))
    def test_20_left_slow_pwm(self):
        p = normalized_to_preview(*lr("TURN_LEFT_SLOW")); self.assertIn(p["pwm_ch1"], (1622, 1623)); self.assertIn(p["pwm_ch3"], (1622, 1623))
    def test_21_right_slow_pwm(self):
        p = normalized_to_preview(*lr("TURN_RIGHT_SLOW")); self.assertIn(p["pwm_ch1"], (1377, 1378)); self.assertIn(p["pwm_ch3"], (1622, 1623))
    def test_22_stale_not_ready(self): self.assertFalse(ready(left_fresh=False))
    def test_23_failsafe_not_ready(self): self.assertFalse(ready(failsafe_active=True))
    def test_24_dry_run_not_ready(self): self.assertFalse(ready(dry_run=True))
    def test_25_interface_not_ready(self): self.assertFalse(ready(external_interface_confirmed=False))
    def test_26_arbitration_not_ready(self): self.assertFalse(ready(external_arbitration_confirmed=False))
    def test_27_manual_takeover_blocked(self): self.assertFalse(takeover_request_allowed(False, require_ready=True))
    def test_28_all_ready_conditions_true(self): self.assertTrue(ready())
    def test_29_disabled_not_ready(self): self.assertFalse(ready(enabled=False))
    def test_30_right_stale_not_ready(self): self.assertFalse(ready(right_fresh=False))
    def test_31_safe_stale_not_ready(self): self.assertFalse(ready(command_fresh=False))
    def test_32_hardware_disabled_not_ready(self): self.assertFalse(ready(hardware_output_enabled=False))
    def test_33_preview_has_no_paho_import(self): self.assertNotIn("paho", PREVIEW_NODE.read_text().lower())
    def test_34_preview_has_no_mqtt_string(self): self.assertNotIn("mqtt", PREVIEW_NODE.read_text().lower())
    def test_35_preview_has_no_rc_override_publisher(self): self.assertNotIn("/mavros/rc/override", PREVIEW_NODE.read_text())
    def test_36_preview_has_no_external_thruster_publisher(self): self.assertNotIn("seano/USV-001/thruster", PREVIEW_NODE.read_text())
    def test_37_pool_disables_mavros(self): self.assertIn("use_mavros:=false", POOL_SCRIPT.read_text())
    def test_38_pool_disables_rc_bridge(self): self.assertIn("use_rc_override_bridge:=false", POOL_SCRIPT.read_text())
    def test_39_pool_forces_dry_run(self): self.assertIn("thruster_preview_dry_run:=true", POOL_SCRIPT.read_text())
    def test_40_pool_disables_hardware(self): self.assertIn("hardware_output_enabled:=false", POOL_SCRIPT.read_text())
    def test_41_pool_interface_unconfirmed(self): self.assertIn("external_interface_confirmed:=false", POOL_SCRIPT.read_text())
    def test_42_pool_arbitration_unconfirmed(self): self.assertIn("external_arbitration_confirmed:=false", POOL_SCRIPT.read_text())
    def test_43_default_path_ready_false(self):
        self.assertIn("self.actuator_path_ready = False", MODE_MANAGER.read_text())
        self.assertIn("self.actuator_path_ready = False", AUTO_MANAGER.read_text())
    def test_44_stale_ready_gate_closes(self):
        self.assertFalse(actuator_path_gate_open(actuator_path_ready=True, ready_received_at=1.0, now=3.0, timeout_s=1.0, require_ready=True))
    def test_45_fresh_ready_gate_opens(self):
        self.assertTrue(actuator_path_gate_open(actuator_path_ready=True, ready_received_at=2.5, now=3.0, timeout_s=1.0, require_ready=True))
    def test_46_other_profiles_keep_legacy_gate(self):
        self.assertTrue(actuator_path_gate_open(actuator_path_ready=False, ready_received_at=0.0, now=3.0, timeout_s=1.0, require_ready=False))
    def test_47_mode_request_has_final_ready_guard(self):
        source = MODE_MANAGER.read_text(); method = source[source.index("    def _request_mode"):]
        self.assertLess(method.index("if not self._actuator_takeover_allowed()"), method.index("self.cli_set_mode.call_async"))
    def test_48_unknown_command_reason_is_visible(self):
        self.assertIn("UNKNOWN_COMMAND_FAILSAFE", AUTO_MANAGER.read_text())
    def test_49_preview_timeout_reports_blocked_reason(self):
        ok, reason = evaluate_actuator_path_ready(enabled=True, left_fresh=False, right_fresh=True,
            command_fresh=False, failsafe_active=False, dry_run=False,
            external_interface_confirmed=True, external_arbitration_confirmed=True,
            hardware_output_enabled=True)
        self.assertFalse(ok); self.assertIn("LEFT_INPUT_STALE", reason); self.assertIn("SAFE_COMMAND_STALE", reason)
    def test_50_hold_is_preview_only_when_hardware_disabled(self):
        self.assertEqual(lr("HOLD_COURSE"), (0.0, 0.0)); self.assertFalse(ready(hardware_output_enabled=False))
    def test_51_stop_is_not_release(self):
        self.assertNotEqual(normalize_command_details("STOP")[0], normalize_command_details("HOLD_COURSE")[0])
        self.assertEqual(lr("STOP"), lr("HOLD_COURSE"))
    def test_52_preview_is_not_applied_when_hardware_false(self):
        preview_exists = normalized_to_preview(*lr("TURN_LEFT"))["steering"] != 0.0
        applied = ready(hardware_output_enabled=False)
        self.assertTrue(preview_exists); self.assertFalse(applied)
    def test_53_no_mqtt_credentials_in_runtime_changes(self):
        text = "\n".join(path.read_text().lower() for path in
            (PREVIEW_NODE, PACKAGE_ROOT / "seano_vision" / "thruster_preview.py", PHASE7_LAUNCH, POOL_SCRIPT))
        for token in ("mqtt_password", "broker_password", "mqtt_username", "client_secret"):
            self.assertNotIn(token, text)
    def test_54_preview_automatically_requires_ready_gate(self):
        source = PHASE7_LAUNCH.read_text()
        self.assertIn("effective_require_actuator_path_ready = _any_true(", source)
        self.assertIn("use_thruster_adapter_preview, require_actuator_path_ready", source)


if __name__ == "__main__":
    unittest.main()
