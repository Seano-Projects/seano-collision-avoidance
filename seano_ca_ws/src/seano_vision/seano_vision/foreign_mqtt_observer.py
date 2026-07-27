"""Read-only observer for foreign messages on the shared thruster topic.

Only an allowlisted metadata record is emitted. Raw payloads and credential
values are never logged, and this module intentionally has no publish API or
ROS dependency.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import sys
import threading
import time
from typing import Any, Mapping, TextIO

from .secure_mqtt_credentials import (
    CredentialError,
    MqttCredentials,
    load_credentials,
)


SHARED_TOPIC = "seano/USV-001/thruster"
BENIGN_RELEASE = "BENIGN_RELEASE"
BENIGN_NEUTRAL = "BENIGN_NEUTRAL"
ACTIVE_FOREIGN_COMMAND = "ACTIVE_FOREIGN_COMMAND"
UNKNOWN_SCHEMA = "UNKNOWN_SCHEMA"
CLASSIFICATIONS = (
    BENIGN_RELEASE,
    BENIGN_NEUTRAL,
    ACTIVE_FOREIGN_COMMAND,
    UNKNOWN_SCHEMA,
)
ZERO_EPSILON = 1e-9


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe_identifier(value: Any) -> str | None:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    text = " ".join(str(value).split())
    return text[:128] if text else None


def classify_payload(payload: Any) -> str:
    """Classify only the release/throttle/steering allowlist."""
    if not isinstance(payload, Mapping):
        return UNKNOWN_SCHEMA
    throttle = _finite_number(payload.get("throttle"))
    steering = _finite_number(payload.get("steering"))
    release = payload.get("release") is True
    if (
        (throttle is not None and abs(throttle) > ZERO_EPSILON)
        or (steering is not None and abs(steering) > ZERO_EPSILON)
    ):
        return ACTIVE_FOREIGN_COMMAND
    if release:
        return BENIGN_RELEASE
    if (
        throttle is not None
        and steering is not None
        and abs(throttle) <= ZERO_EPSILON
        and abs(steering) <= ZERO_EPSILON
    ):
        return BENIGN_NEUTRAL
    return UNKNOWN_SCHEMA


@dataclass(frozen=True)
class Observation:
    timestamp: float
    source: str | None
    session_id: str | None
    release: bool
    throttle: float | None
    steering: float | None
    retained: bool
    qos: int
    payload_hash: str
    classification: str


def inspect_message(
    raw_payload: bytes,
    *,
    retained: bool,
    qos: int,
    timestamp: float | None = None,
) -> Observation:
    payload: Any
    try:
        payload = json.loads(raw_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        payload = None
    mapping = payload if isinstance(payload, Mapping) else {}
    return Observation(
        timestamp=time.time() if timestamp is None else float(timestamp),
        source=_safe_identifier(mapping.get("source")),
        session_id=_safe_identifier(mapping.get("session_id")),
        release=mapping.get("release") is True,
        throttle=_finite_number(mapping.get("throttle")),
        steering=_finite_number(mapping.get("steering")),
        retained=bool(retained),
        qos=int(qos),
        payload_hash=hashlib.sha256(raw_payload).hexdigest(),
        classification=classify_payload(payload),
    )


class ObservationSummary:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.maximum_absolute_throttle = 0.0
        self.maximum_absolute_steering = 0.0

    def add(self, observation: Observation) -> None:
        self.counts[observation.classification] += 1
        if observation.throttle is not None:
            self.maximum_absolute_throttle = max(
                self.maximum_absolute_throttle, abs(observation.throttle)
            )
        if observation.steering is not None:
            self.maximum_absolute_steering = max(
                self.maximum_absolute_steering, abs(observation.steering)
            )

    def as_dict(self) -> dict[str, Any]:
        total = sum(self.counts.values())
        active = self.counts[ACTIVE_FOREIGN_COMMAND]
        unknown = self.counts[UNKNOWN_SCHEMA]
        return {
            "total_message": total,
            "neutral_count": self.counts[BENIGN_NEUTRAL],
            "release_count": self.counts[BENIGN_RELEASE],
            "active_count": active,
            "unknown_count": unknown,
            "maximum_absolute_throttle": self.maximum_absolute_throttle,
            "maximum_absolute_steering": self.maximum_absolute_steering,
            "safe_for_neutral_message_tolerance": (
                total > 0 and active == 0 and unknown == 0
            ),
        }


def create_read_only_client(credentials: MqttCredentials):
    import paho.mqtt.client as mqtt

    client_id = f"ca-foreign-observer-{secrets.token_hex(6)}"
    try:
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION1,
            client_id=client_id,
        )
    except (AttributeError, TypeError):
        client = mqtt.Client(client_id=client_id)
    client.username_pw_set(credentials.username, credentials.password)
    client.tls_set(ca_certs=credentials.ca_cert or None)
    client.tls_insecure_set(False)
    return client


class ForeignMqttObserver:
    """MQTT subscriber with no publish method and no ROS integration."""

    def __init__(
        self,
        *,
        client,
        host: str,
        port: int,
        log_stream: TextIO,
        output_stream: TextIO,
    ) -> None:
        self.client = client
        self.host = host
        self.port = int(port)
        self.log_stream = log_stream
        self.output_stream = output_stream
        self.connected = threading.Event()
        self.connection_failed = threading.Event()
        self.summary = ObservationSummary()
        self._lock = threading.Lock()
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc, *extra) -> None:
        try:
            success = int(rc) == 0
        except (TypeError, ValueError):
            success = bool(getattr(rc, "is_failure", True)) is False
        if not success:
            self.connection_failed.set()
            return
        result = client.subscribe(SHARED_TOPIC, qos=1)
        result_code = result[0] if isinstance(result, tuple) else result
        if int(result_code) != 0:
            self.connection_failed.set()
            return
        self.connected.set()

    def _on_disconnect(self, client, userdata, rc, *extra) -> None:
        self.connected.clear()

    def _on_message(self, client, userdata, message) -> None:
        observation = inspect_message(
            bytes(message.payload),
            retained=bool(getattr(message, "retain", False)),
            qos=int(getattr(message, "qos", 0)),
        )
        record = asdict(observation)
        encoded = json.dumps(record, separators=(",", ":"), sort_keys=True)
        with self._lock:
            self.summary.add(observation)
            self.log_stream.write(encoded + "\n")
            self.log_stream.flush()
            self.output_stream.write("OBSERVATION " + encoded + "\n")
            self.output_stream.flush()

    def observe(self, duration_s: float, connection_timeout_s: float = 10.0) -> None:
        self.client.connect_async(self.host, self.port, keepalive=10)
        self.client.loop_start()
        try:
            deadline = time.monotonic() + float(connection_timeout_s)
            while not self.connected.wait(0.05):
                if self.connection_failed.is_set():
                    raise RuntimeError("MQTT_SUBSCRIBE_FAILED")
                if time.monotonic() >= deadline:
                    raise RuntimeError("MQTT_CONNECTION_TIMEOUT")
            threading.Event().wait(float(duration_s))
        finally:
            try:
                self.client.disconnect()
            finally:
                self.client.loop_stop()


def _validated_log_file(log_dir: str, repo_root: Path) -> Path:
    repo = repo_root.resolve(strict=True)
    directory = Path(log_dir).resolve()
    if directory == repo or repo not in directory.parents:
        raise ValueError("OBSERVER_LOG_DIR_OUTSIDE_REPO")
    if directory.exists():
        raise ValueError("OBSERVER_LOG_DIR_ALREADY_EXISTS")
    directory.mkdir(parents=True, mode=0o700)
    return directory / "foreign_mqtt_observations.jsonl"


def _print_summary(summary: Mapping[str, Any], stream: TextIO) -> None:
    stream.write("FOREIGN MQTT OBSERVER SUMMARY\n")
    for key in (
        "total_message",
        "neutral_count",
        "release_count",
        "active_count",
        "unknown_count",
        "maximum_absolute_throttle",
        "maximum_absolute_steering",
        "safe_for_neutral_message_tolerance",
    ):
        stream.write(f"{key}: {summary[key]}\n")
    stream.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--log-dir", required=True)
    parser.add_argument("--duration", type=float, default=30.0)
    args = parser.parse_args()
    try:
        repo_root = Path(args.repo_root)
        credentials = load_credentials(args.source, repo_root)
        log_file = _validated_log_file(args.log_dir, repo_root)
        client = create_read_only_client(credentials)
        print(f"Observation log: {log_file}")
        file_descriptor = os.open(
            log_file,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as stream:
            observer = ForeignMqttObserver(
                client=client,
                host=credentials.host,
                port=credentials.port,
                log_stream=stream,
                output_stream=sys.stdout,
            )
            observer.observe(args.duration)
            _print_summary(observer.summary.as_dict(), sys.stdout)
        return 0
    except (CredentialError, OSError, RuntimeError, ValueError) as exc:
        print(f"FOREIGN MQTT OBSERVER ERROR: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
