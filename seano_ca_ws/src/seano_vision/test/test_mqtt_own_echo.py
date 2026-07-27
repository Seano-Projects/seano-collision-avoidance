"""Race and classification tests using only an in-memory fake MQTT client."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest

from seano_vision.thruster_test_safety import (
    ACTIVE_FOREIGN_COMMAND,
    AdapterCore,
    BENIGN_NEUTRAL,
    BENIGN_RELEASE,
    OWN_MQTT_ECHO,
    GuardianCore,
    GuardianInputs,
    OwnMessageRegistry,
    StaticGates,
    TestLimits as Limits,
    UNKNOWN_SCHEMA,
    classify_mqtt_message,
    publish_action_tracked,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_NODE = (
    PACKAGE_ROOT / "seano_vision" / "guarded_thruster_test_adapter_node.py"
)
TRANSPORT = PACKAGE_ROOT / "seano_vision" / "thruster_test_mqtt.py"
BASELINE = PACKAGE_ROOT.parents[1] / "run_pool_existing_control_path.sh"


class Clock:
    def __init__(self):
        self.value = 10.0

    def __call__(self):
        return self.value


class EchoBeforeReturnTransport:
    connected = True

    def __init__(self, registry, *, fail=False):
        self.registry = registry
        self.fail = fail
        self.classifications = []
        self.publish_calls = 0

    def publish(self, topic, payload, qos, retain):
        self.publish_calls += 1
        if self.fail:
            raise ConnectionError("fake publish failure")
        self.classifications.append(
            classify_mqtt_message(payload, qos=qos, own_registry=self.registry)
        )
        return type("Info", (), {"mid": 42})()


def prepared_action(kind):
    core = AdapterCore(session_id=f"session-{kind.lower()}")
    if kind == "RELEASE":
        return core.abort("TEST", foreign=True)[0]
    if kind == "NEUTRAL":
        return core.update("STOP", 0.0, 0.0, True, now=1.0)[0]
    return core.update("SLOW_DOWN", 0.1, 0.1, True, now=1.0)[0]


def serialized(action):
    return json.dumps(action.payload, separators=(",", ":"), sort_keys=True)


def test_local_echo_before_publish_returns_is_own():
    registry = OwnMessageRegistry()
    transport = EchoBeforeReturnTransport(registry)
    publish_action_tracked(transport, registry, prepared_action("RELEASE"))
    assert transport.classifications[0].classification == OWN_MQTT_ECHO
    assert transport.classifications[0].matched_pending_own


def test_local_echo_before_publish_ack_is_not_foreign():
    registry = OwnMessageRegistry()
    action = prepared_action("MOTION")
    transport = EchoBeforeReturnTransport(registry)
    tracked = publish_action_tracked(transport, registry, action)
    assert transport.classifications[0].classification == OWN_MQTT_ECHO
    ack = registry.acknowledge(tracked.mid)
    assert ack.matched_completed_own


@pytest.mark.parametrize("kind", ["RELEASE", "NEUTRAL", "MOTION"])
def test_own_release_neutral_and_motion_echo_do_not_abort(kind):
    registry = OwnMessageRegistry()
    action = prepared_action(kind)
    transport = EchoBeforeReturnTransport(registry)
    publish_action_tracked(transport, registry, action)
    message = transport.classifications[0]
    core = AdapterCore(session_id="decision-core")
    assert message.classification == OWN_MQTT_ECHO
    assert core.handle_classified(message) == []
    assert not core.aborted


def test_same_sequence_from_other_session_is_not_own():
    registry = OwnMessageRegistry()
    action = prepared_action("NEUTRAL")
    transport = EchoBeforeReturnTransport(registry)
    publish_action_tracked(transport, registry, action)
    other = dict(action.payload, session_id="different-session")
    message = classify_mqtt_message(
        json.dumps(other, separators=(",", ":"), sort_keys=True),
        own_registry=registry,
    )
    assert message.classification == BENIGN_NEUTRAL
    assert not message.matched_pending_own
    assert not message.matched_completed_own


def test_identical_hash_after_expiry_is_not_own():
    clock = Clock()
    registry = OwnMessageRegistry(
        pending_ttl_s=0.1,
        completed_grace_s=0.1,
        clock=clock,
    )
    action = prepared_action("MOTION")

    class NoEchoTransport:
        connected = True

        def publish(self, topic, payload, qos, retain):
            return type("Info", (), {"mid": 9})()

    publish_action_tracked(NoEchoTransport(), registry, action)
    clock.value += 1.0
    message = classify_mqtt_message(
        serialized(action),
        own_registry=registry,
    )
    assert message.classification == ACTIVE_FOREIGN_COMMAND
    assert not message.matched_pending_own
    assert not message.matched_completed_own


def test_publish_failure_removes_pending_entry_and_fails_closed():
    registry = OwnMessageRegistry()
    transport = EchoBeforeReturnTransport(registry, fail=True)
    with pytest.raises(ConnectionError):
        publish_action_tracked(transport, registry, prepared_action("MOTION"))
    assert registry.counts() == (0, 0)
    adapter_source = ADAPTER_NODE.read_text(encoding="utf-8")
    assert "self.core.aborted = True" in adapter_source
    assert "self.core.held = False" in adapter_source


def test_concurrent_on_message_matching_is_lock_safe():
    registry = OwnMessageRegistry()
    action = prepared_action("MOTION")

    class NoEchoTransport:
        connected = True

        def publish(self, topic, payload, qos, retain):
            return type("Info", (), {"mid": 17})()

    publish_action_tracked(NoEchoTransport(), registry, action)
    raw = serialized(action)
    with ThreadPoolExecutor(max_workers=8) as executor:
        messages = list(
            executor.map(
                lambda _: classify_mqtt_message(raw, own_registry=registry),
                range(32),
            )
        )
    assert all(message.classification == OWN_MQTT_ECHO for message in messages)
    assert sum(message.matched_pending_own for message in messages) == 1
    assert sum(message.matched_completed_own for message in messages) == 31


def test_hold_course_before_control_publishes_nothing():
    core = AdapterCore(session_id="hold-before")
    assert core.update("HOLD_COURSE", 0.0, 0.0, True, now=1.0) == []
    assert core.shutdown(now=2.0) == []


def test_hold_course_after_control_is_bounded_neutral_release():
    core = AdapterCore(session_id="hold-after")
    core.update("SLOW_DOWN", 0.1, 0.1, True, now=1.0)
    actions = core.update("HOLD_COURSE", 0.0, 0.0, True, now=2.0)
    assert [action.kind for action in actions] == ["NEUTRAL", "RELEASE"]
    assert core.update("HOLD_COURSE", 0.0, 0.0, True, now=3.0) == []
    assert core.shutdown(now=4.0) == []


@pytest.mark.parametrize(
    "payload",
    (
        {"source": "SeaPortal", "throttle": 1.0, "steering": 0.0},
        {"source": "SeaPortal", "throttle": 0.0, "steering": -1.0},
    ),
)
def test_external_nonzero_command_aborts(payload):
    message = classify_mqtt_message(json.dumps(payload))
    core = AdapterCore(session_id="external-active")
    assert message.classification == ACTIVE_FOREIGN_COMMAND
    assert [action.kind for action in core.handle_classified(message)] == [
        "RELEASE"
    ]
    assert core.aborted
    assert core.abort_reason == "FOREIGN_ACTIVE_COMMAND"


def test_unknown_schema_aborts():
    message = classify_mqtt_message('{"command":"FORWARD"}')
    core = AdapterCore(session_id="external-unknown")
    assert message.classification == UNKNOWN_SCHEMA
    assert [action.kind for action in core.handle_classified(message)] == [
        "RELEASE"
    ]
    assert core.abort_reason == "FOREIGN_UNKNOWN_SCHEMA"


def test_guardian_preserves_classified_foreign_reason():
    guardian = GuardianCore(
        StaticGates(
            hardware_test_enabled=True,
            mqtt_publish_enabled=True,
            operator_confirmed=True,
            shared_mqtt_test_confirmed=True,
            tether_confirmed=True,
            emergency_stop_confirmed=True,
            exclusive_test_window_confirmed=True,
            foreign_command_monitor_enabled=True,
        ),
        Limits(),
        observation_window_s=0.0,
        startup_grace_s=0.0,
    )
    decision = guardian.evaluate(
        GuardianInputs(
            now=10.0,
            started_at=0.0,
            foreign_command=True,
            foreign_command_reason="FOREIGN_ACTIVE_COMMAND",
        )
    )
    assert decision.abort_reason == "FOREIGN_ACTIVE_COMMAND"


def test_benign_external_release_and_neutral_do_not_abort():
    core = AdapterCore(session_id="benign")
    for raw, expected in (
        ('{"release":true}', BENIGN_RELEASE),
        ('{"throttle":0,"steering":0}', BENIGN_NEUTRAL),
    ):
        message = classify_mqtt_message(raw)
        assert message.classification == expected
        assert core.handle_classified(message) == []
    assert not core.aborted


def test_retained_message_from_old_session_is_not_own_and_blocks():
    registry = OwnMessageRegistry()
    action = prepared_action("RELEASE")
    transport = EchoBeforeReturnTransport(registry)
    publish_action_tracked(transport, registry, action)
    retained = classify_mqtt_message(
        serialized(action),
        retained=True,
        qos=1,
        own_registry=registry,
    )
    core = AdapterCore(session_id="retained")
    assert retained.classification == BENIGN_RELEASE
    assert not retained.matched_pending_own
    assert core.handle_classified(retained)[0].kind == "RELEASE"
    assert core.abort_reason == "FOREIGN_RETAINED_MESSAGE"


def test_logging_metadata_exists_without_raw_payload_or_credentials():
    source = ADAPTER_NODE.read_text(encoding="utf-8")
    for field in (
        "MQTT_MESSAGE_CLASSIFIED",
        "classification",
        "matched_pending_own",
        "matched_completed_own",
        "pending_age_s",
        "FOREIGN_ACTIVE_COMMAND",
        "FOREIGN_UNKNOWN_SCHEMA",
    ):
        assert field in source
    assert '"raw_payload"' not in source
    assert "SEANO_MQTT_PASSWORD" not in source


def test_fake_tests_open_no_broker_or_ros_hardware_runtime():
    test_source = Path(__file__).read_text(encoding="utf-8")
    transport_source = TRANSPORT.read_text(encoding="utf-8")
    assert "paho." + "mqtt" not in test_source
    assert ".con" + "nect(" not in test_source
    assert "rcl" + "py" not in test_source
    assert "ros2 " + "launch" not in test_source
    assert "create_publisher(OverrideRCIn" not in transport_source


def test_baseline_control_path_is_not_changed_by_echo_correlation():
    baseline = BASELINE.read_text(encoding="utf-8")
    assert "use_guarded_thruster_test_adapter:=false" in baseline
    assert "hardware_test_enabled:=false" in baseline
