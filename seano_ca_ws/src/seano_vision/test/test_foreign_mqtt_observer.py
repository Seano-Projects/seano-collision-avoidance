"""Fake-MQTT tests for the read-only foreign command observer."""

import io
import json
from pathlib import Path
import types

from seano_vision.foreign_mqtt_observer import (
    ACTIVE_FOREIGN_COMMAND,
    BENIGN_NEUTRAL,
    BENIGN_RELEASE,
    ForeignMqttObserver,
    SHARED_TOPIC,
    UNKNOWN_SCHEMA,
    classify_payload,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
OBSERVER_SOURCE = PACKAGE_ROOT / "seano_vision" / "foreign_mqtt_observer.py"
HARDWARE_SCRIPT = PACKAGE_ROOT.parents[1] / "run_pool_thruster_hardware_test.sh"


class FakeClient:
    def __init__(self):
        self.publish_calls = []
        self.subscribe_calls = []
        self.connect_calls = []
        self.disconnect_calls = 0

    def connect_async(self, host, port, keepalive):
        self.connect_calls.append((host, port, keepalive))

    def loop_start(self):
        self.on_connect(self, None, {}, 0)

    def subscribe(self, topic, qos):
        self.subscribe_calls.append((topic, qos))
        return (0, 1)

    def publish(self, *args, **kwargs):
        self.publish_calls.append((args, kwargs))
        raise AssertionError("read-only observer attempted MQTT publish")

    def disconnect(self):
        self.disconnect_calls += 1

    def loop_stop(self):
        pass


def make_observer():
    client = FakeClient()
    log = io.StringIO()
    output = io.StringIO()
    observer = ForeignMqttObserver(
        client=client,
        host="fake-broker.invalid",
        port=8883,
        log_stream=log,
        output_stream=output,
    )
    return observer, client, log, output


def deliver(client, payload, *, retained=False, qos=1):
    message = types.SimpleNamespace(
        payload=json.dumps(payload).encode("utf-8"),
        retain=retained,
        qos=qos,
    )
    client.on_message(client, None, message)


def test_release_is_benign():
    assert classify_payload({"release": True}) == BENIGN_RELEASE


def test_zero_throttle_and_steering_are_benign():
    assert classify_payload({"throttle": 0, "steering": 0}) == BENIGN_NEUTRAL


def test_nonzero_throttle_is_active():
    assert (
        classify_payload({"throttle": 0.1, "steering": 0})
        == ACTIVE_FOREIGN_COMMAND
    )


def test_nonzero_steering_is_active():
    assert (
        classify_payload({"throttle": 0, "steering": -0.1})
        == ACTIVE_FOREIGN_COMMAND
    )


def test_unknown_schema_is_unknown():
    assert classify_payload({"command": "FORWARD"}) == UNKNOWN_SCHEMA


def test_fake_observer_subscribes_and_never_publishes():
    observer, client, _, _ = make_observer()
    observer.observe(duration_s=0.0, connection_timeout_s=0.1)
    assert client.subscribe_calls == [(SHARED_TOPIC, 1)]
    assert client.publish_calls == []
    assert client.disconnect_calls == 1
    assert not hasattr(observer, "publish")


def test_observer_has_no_ros_runtime_and_script_exits_before_ros_path():
    source = OBSERVER_SOURCE.read_text(encoding="utf-8")
    script = HARDWARE_SCRIPT.read_text(encoding="utf-8")
    assert "rclpy" not in source
    assert "ros2" not in source
    observer_branch = script.index('if [ "${1:-}" = "--foreign-observe-only" ]')
    ros_runtime = script.index("source /opt/ros/humble/setup.bash")
    assert observer_branch < ros_runtime
    assert "--duration 30" in script


def test_sensitive_payload_fields_and_credentials_are_never_logged():
    observer, client, log, output = make_observer()
    secret_values = (
        "fake-password-must-not-log",
        "fake-token-must-not-log",
        "fake-username-must-not-log",
    )
    deliver(
        client,
        {
            "source": "SeaPortal",
            "session_id": "portal-session",
            "release": False,
            "throttle": 0,
            "steering": 0,
            "password": secret_values[0],
            "token": secret_values[1],
            "username": secret_values[2],
        },
        retained=True,
        qos=1,
    )
    recorded = log.getvalue() + output.getvalue()
    for secret in secret_values:
        assert secret not in recorded
    record = json.loads(log.getvalue())
    assert set(record) == {
        "classification",
        "payload_hash",
        "qos",
        "release",
        "retained",
        "session_id",
        "source",
        "steering",
        "throttle",
        "timestamp",
    }


def test_summary_reports_counts_maxima_and_tolerance_decision():
    observer, client, _, _ = make_observer()
    deliver(client, {"release": True})
    deliver(client, {"throttle": 0, "steering": 0})
    benign = observer.summary.as_dict()
    assert benign["total_message"] == 2
    assert benign["release_count"] == 1
    assert benign["neutral_count"] == 1
    assert benign["safe_for_neutral_message_tolerance"] is True

    deliver(client, {"throttle": -4.5, "steering": 2.0})
    active = observer.summary.as_dict()
    assert active["active_count"] == 1
    assert active["maximum_absolute_throttle"] == 4.5
    assert active["maximum_absolute_steering"] == 2.0
    assert active["safe_for_neutral_message_tolerance"] is False
