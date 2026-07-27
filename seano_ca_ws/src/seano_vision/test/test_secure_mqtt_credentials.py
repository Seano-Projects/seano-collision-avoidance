import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from unittest import mock

import yaml

from seano_vision.secure_mqtt_credentials import CredentialError, load_credentials
from seano_vision.thruster_test_mqtt import PahoSharedTopicTransport


REPO_ROOT = Path(__file__).resolve().parents[4]
HARDWARE_SCRIPT = REPO_ROOT / "seano_ca_ws" / "run_pool_thruster_hardware_test.sh"
BASELINE_SCRIPT = REPO_ROOT / "seano_ca_ws" / "run_pool_existing_control_path.sh"

FAKE_HOST = "fake-broker.invalid"
FAKE_USERNAME = "fake-user-do-not-print"
FAKE_PASSWORD = "fake-password-do-not-print"


def yaml_text(**overrides):
    mqtt = {
        "host": FAKE_HOST,
        "port": 8883,
        "username": FAKE_USERNAME,
        "password": FAKE_PASSWORD,
        "tls": True,
        "tls_insecure": False,
    }
    mqtt.update(overrides)
    return yaml.safe_dump({
        "/**": {
            "ros__parameters": {
                "mqtt": mqtt,
                "vehicle": {"id": "FAKE-001"},
            }
        }
    }, sort_keys=False)


class SecureCredentialLoaderTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.source = self.root / "credentials.yaml"
        self.source.write_text(yaml_text(), encoding="utf-8")

    def tearDown(self):
        self.tempdir.cleanup()

    def load(self, source=None, env=None):
        return load_credentials(str(source or self.source), REPO_ROOT, env or {})

    def test_01_yaml_uses_safe_load(self):
        with mock.patch(
            "seano_vision.secure_mqtt_credentials.yaml.safe_load",
            wraps=yaml.safe_load,
        ) as safe_load:
            self.assertTrue(self.load().ready)
        safe_load.assert_called_once()

    def test_02_missing_yaml_is_rejected(self):
        with self.assertRaises(CredentialError):
            self.load(self.root / "missing.yaml")

    def test_03_symlink_source_is_rejected(self):
        link = self.root / "credential-link.yaml"
        link.symlink_to(self.source)
        with self.assertRaisesRegex(CredentialError, "SYMLINK_REJECTED"):
            self.load(link)

    def test_04_missing_host_is_rejected(self):
        self.source.write_text(yaml_text(host=""), encoding="utf-8")
        with self.assertRaisesRegex(CredentialError, "HOST_REQUIRED"):
            self.load()

    def test_05_missing_username_is_rejected(self):
        self.source.write_text(yaml_text(username=""), encoding="utf-8")
        with self.assertRaisesRegex(CredentialError, "USERNAME_REQUIRED"):
            self.load()

    def test_06_missing_password_is_rejected(self):
        self.source.write_text(yaml_text(password=""), encoding="utf-8")
        with self.assertRaisesRegex(CredentialError, "PASSWORD_REQUIRED"):
            self.load()

    def test_07_tls_false_is_rejected(self):
        self.source.write_text(yaml_text(tls=False), encoding="utf-8")
        with self.assertRaisesRegex(CredentialError, "TLS_REQUIRED"):
            self.load()

    def test_08_tls_insecure_is_rejected(self):
        self.source.write_text(yaml_text(tls_insecure=True), encoding="utf-8")
        with self.assertRaisesRegex(CredentialError, "TLS_INSECURE_REJECTED"):
            self.load()

    def test_09_environment_override_has_priority(self):
        credentials = self.load(env={
            "SEANO_MQTT_HOST": "override-host.invalid",
            "SEANO_MQTT_PORT": "9443",
            "SEANO_MQTT_USERNAME": "override-user",
            "SEANO_MQTT_PASSWORD": "override-password",
        })
        self.assertEqual(credentials.host, "override-host.invalid")
        self.assertEqual(credentials.port, 9443)
        self.assertEqual(credentials.username, "override-user")
        self.assertEqual(credentials.password, "override-password")

    def test_10_credential_check_never_prints_values_or_creates_logs(self):
        runtime = self.root / "runtime-must-not-exist"
        env = dict(os.environ, SEANO_MQTT_ENV_FILE=str(self.source), SEANO_CA_RUNTIME_DIR=str(runtime))
        result = subprocess.run(
            [str(HARDWARE_SCRIPT), "--credential-check"], env=env,
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Ready: true", result.stdout)
        for value in (FAKE_HOST, FAKE_USERNAME, FAKE_PASSWORD):
            self.assertNotIn(value, result.stdout + result.stderr)
        self.assertFalse(runtime.exists())


class PreflightOnlyTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.source = self.root / "credentials.yaml"
        self.source.write_text(yaml_text(), encoding="utf-8")
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()
        self.calls = self.root / "ros2-calls.txt"
        fake_ros2 = self.fake_bin / "ros2"
        fake_ros2.write_text(textwrap.dedent("""\
            #!/usr/bin/env bash
            printf '%s\\n' "$*" >> "$FAKE_ROS2_CALLS"
            case "$*" in
              "node list") printf '%s\\n' "${FAKE_NODE_LIST:-/usv/thruster}" ;;
              "topic echo /mavros/state --once")
                printf 'connected: true\\narmed: %s\\nmode: RTL\\n' "${FAKE_FCU_ARMED:-false}" ;;
              "topic info -v /mavros/rc/override")
                printf 'Publisher count: %s\\n' "${FAKE_PUBLISHER_COUNT:-1}"
                printf 'Node name: %s\\n' "${FAKE_PUBLISHER_NAME:-thruster}"
                printf 'Node namespace: %s\\n' "${FAKE_PUBLISHER_NAMESPACE:-/usv}"
                printf 'Subscription count: 1\\nNode name: rc\\nNode namespace: /mavros\\n' ;;
              *) exit 90 ;;
            esac
        """), encoding="utf-8")
        fake_ros2.chmod(fake_ros2.stat().st_mode | stat.S_IXUSR)

    def tearDown(self):
        self.tempdir.cleanup()

    def run_preflight(self, **overrides):
        runtime = self.root / "hardware-log-must-not-exist"
        env = dict(
            os.environ,
            PATH=f"{self.fake_bin}:{os.environ['PATH']}",
            SEANO_MQTT_ENV_FILE=str(self.source),
            SEANO_CA_RUNTIME_DIR=str(runtime),
            FAKE_ROS2_CALLS=str(self.calls),
            ROS_DOMAIN_ID="0",
        )
        env.update(overrides)
        result = subprocess.run(
            [str(HARDWARE_SCRIPT), "--preflight-only"], env=env,
            text=True, capture_output=True,
        )
        return result, runtime

    def test_11_preflight_is_read_only_and_secrets_are_not_arguments(self):
        result, runtime = self.run_preflight()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Ready for guarded operator procedure: true", result.stdout)
        calls = self.calls.read_text(encoding="utf-8")
        self.assertNotIn(" launch ", f" {calls} ")
        self.assertNotIn(" run ", f" {calls} ")
        for value in (FAKE_HOST, FAKE_USERNAME, FAKE_PASSWORD):
            self.assertNotIn(value, result.stdout + result.stderr + calls)
        self.assertFalse(runtime.exists())

    def test_12_wrong_rc_publisher_is_not_ready(self):
        result, _ = self.run_preflight(FAKE_PUBLISHER_NAME="other")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Ready for guarded operator procedure: false", result.stdout)

    def test_13_multiple_rc_publishers_are_not_ready(self):
        result, _ = self.run_preflight(FAKE_PUBLISHER_COUNT="2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Ready for guarded operator procedure: false", result.stdout)

    def test_14_armed_fcu_is_not_ready(self):
        result, _ = self.run_preflight(FAKE_FCU_ARMED="true")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FCU armed: true", result.stdout)
        self.assertIn("Ready for guarded operator procedure: false", result.stdout)

    def test_15_active_baseline_node_is_not_ready(self):
        result, _ = self.run_preflight(FAKE_NODE_LIST="/usv/thruster\n/detector_node")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Ready for guarded operator procedure: false", result.stdout)

    def test_16_excessive_limit_is_not_ready(self):
        result, _ = self.run_preflight(CA_TEST_MAX_THROTTLE_PERCENT="10.1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Ready for guarded operator procedure: false", result.stdout)

    def test_17_baseline_has_no_credential_or_mqtt_runtime_path(self):
        text = BASELINE_SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("SEANO_MQTT_ENV_FILE", text)
        self.assertNotIn("SEANO_MQTT_HOST", text)
        self.assertNotIn("PahoSharedTopicTransport", text)
        self.assertIn("use_guarded_thruster_test_adapter:=false", text)
        self.assertIn("mqtt_publish_enabled:=false", text)


class FakeMqttTransportTests(unittest.TestCase):
    def test_18_tls_uses_system_ca_without_opening_connection(self):
        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.connect_calls = []
                self.tls = None

            def username_pw_set(self, username, password):
                self.auth_configured = bool(username and password)

            def tls_set(self, **kwargs):
                self.tls = kwargs

            def tls_insecure_set(self, value):
                self.insecure = value

        fake_client = FakeClient()
        client_module = types.ModuleType("paho.mqtt.client")
        client_module.CallbackAPIVersion = types.SimpleNamespace(VERSION1=1)
        client_module.Client = lambda *args, **kwargs: fake_client
        mqtt_module = types.ModuleType("paho.mqtt")
        mqtt_module.client = client_module
        paho_module = types.ModuleType("paho")
        paho_module.mqtt = mqtt_module
        modules = {
            "paho": paho_module,
            "paho.mqtt": mqtt_module,
            "paho.mqtt.client": client_module,
        }
        env = {
            "SEANO_MQTT_HOST": FAKE_HOST,
            "SEANO_MQTT_PORT": "8883",
            "SEANO_MQTT_USERNAME": FAKE_USERNAME,
            "SEANO_MQTT_PASSWORD": FAKE_PASSWORD,
            "SEANO_MQTT_TLS": "true",
            "SEANO_MQTT_TLS_INSECURE": "false",
        }
        with mock.patch.dict(sys.modules, modules), mock.patch.dict(os.environ, env, clear=True):
            PahoSharedTopicTransport(
                client_id="fake", topic="fake/topic", qos=1,
                on_message=lambda _: None, on_connection=lambda _: None,
                on_ack=lambda _: None,
            )
        self.assertIsNone(fake_client.tls["ca_certs"])
        self.assertFalse(fake_client.insecure)
        self.assertEqual(fake_client.connect_calls, [])


if __name__ == "__main__":
    unittest.main()
