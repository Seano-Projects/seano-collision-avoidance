"""Side-effect-free credential loading for the guarded hardware-test path.

Secret values are returned only to the calling process.  This module never
logs, connects to MQTT, creates files, or includes credential values in error
messages.
"""

from __future__ import annotations

from dataclasses import dataclass
import argparse
import os
from pathlib import Path
from typing import Mapping

import yaml


class CredentialError(ValueError):
    """A credential source is unavailable or fails closed validation."""


@dataclass(frozen=True)
class MqttCredentials:
    source: str
    host: str
    port: int
    username: str
    password: str
    tls: bool
    tls_insecure: bool
    ca_cert: str = ""
    vehicle_id: str = ""

    @property
    def ready(self) -> bool:
        return bool(
            self.host
            and self.port > 0
            and self.username
            and self.password
            and self.tls
            and not self.tls_insecure
        )


def _strict_bool(value, *, default: bool, field: str) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "on"}:
            return True
        if normalized in {"false", "no", "0", "off"}:
            return False
    raise CredentialError(f"INVALID_{field.upper()}")


def _source_path(raw_path: str, repo_root: Path) -> Path:
    if not raw_path:
        raise CredentialError("CREDENTIAL_SOURCE_REQUIRED")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise CredentialError("CREDENTIAL_SOURCE_MUST_BE_ABSOLUTE")
    if path.is_symlink():
        raise CredentialError("CREDENTIAL_SOURCE_SYMLINK_REJECTED")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise CredentialError("CREDENTIAL_SOURCE_UNAVAILABLE") from exc
    if not resolved.is_file() or not os.access(resolved, os.R_OK):
        raise CredentialError("CREDENTIAL_SOURCE_UNREADABLE")
    repo = repo_root.resolve(strict=True)
    if resolved == repo or repo in resolved.parents:
        raise CredentialError("CREDENTIAL_SOURCE_INSIDE_REPO_REJECTED")
    return resolved


def _yaml_parameters(data) -> tuple[dict, dict]:
    if not isinstance(data, dict):
        raise CredentialError("INVALID_YAML_STRUCTURE")
    params = data.get("/**", {}).get("ros__parameters", {})
    if not isinstance(params, dict):
        params = data.get("ros__parameters", data)
    if not isinstance(params, dict):
        raise CredentialError("INVALID_YAML_PARAMETERS")
    mqtt = params.get("mqtt", {})
    vehicle = params.get("vehicle", {})
    if not isinstance(mqtt, dict):
        raise CredentialError("INVALID_MQTT_SECTION")
    return mqtt, vehicle if isinstance(vehicle, dict) else {}


def load_credentials(
    source_path: str,
    repo_root: Path,
    environment: Mapping[str, str] | None = None,
) -> MqttCredentials:
    """Load YAML then apply explicit environment overrides field-by-field."""

    env = os.environ if environment is None else environment
    if source_path:
        source = _source_path(source_path, repo_root)
        try:
            data = yaml.safe_load(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise CredentialError("CREDENTIAL_YAML_INVALID") from exc
        mqtt, vehicle = _yaml_parameters(data)
        source_label = str(source)
    else:
        mqtt, vehicle = {}, {}
        source_label = "process environment"

    def override(name: str, yaml_value):
        value = env.get(name)
        return value if value not in (None, "") else yaml_value

    host = override("SEANO_MQTT_HOST", mqtt.get("host") or mqtt.get("broker") or "")
    username = override("SEANO_MQTT_USERNAME", mqtt.get("username") or "")
    password = override("SEANO_MQTT_PASSWORD", mqtt.get("password") or "")
    port_raw = override("SEANO_MQTT_PORT", mqtt.get("port"))
    ca_cert = override(
        "SEANO_MQTT_CA_CERT",
        mqtt.get("ca_cert") or mqtt.get("ca_certificate") or mqtt.get("ca_certificate_path") or "",
    )
    tls_raw = override("SEANO_MQTT_TLS", mqtt.get("tls", mqtt.get("use_tls", True)))
    insecure_raw = override(
        "SEANO_MQTT_TLS_INSECURE", mqtt.get("tls_insecure", False)
    )

    try:
        port = int(port_raw)
    except (TypeError, ValueError) as exc:
        raise CredentialError("MQTT_PORT_REQUIRED_OR_INVALID") from exc
    if not 1 <= port <= 65535:
        raise CredentialError("MQTT_PORT_OUT_OF_RANGE")

    credentials = MqttCredentials(
        source=source_label,
        host=str(host or ""),
        port=port,
        username=str(username or ""),
        password=str(password or ""),
        tls=_strict_bool(tls_raw, default=True, field="mqtt_tls"),
        tls_insecure=_strict_bool(
            insecure_raw, default=False, field="mqtt_tls_insecure"
        ),
        ca_cert=str(ca_cert or ""),
        vehicle_id=str(vehicle.get("id") or ""),
    )
    if not credentials.host:
        raise CredentialError("MQTT_HOST_REQUIRED")
    if not credentials.username:
        raise CredentialError("MQTT_USERNAME_REQUIRED")
    if not credentials.password:
        raise CredentialError("MQTT_PASSWORD_REQUIRED")
    if not credentials.tls:
        raise CredentialError("MQTT_TLS_REQUIRED")
    if credentials.tls_insecure:
        raise CredentialError("MQTT_TLS_INSECURE_REJECTED")
    return credentials


def _emit_nul(fields: list[str]) -> None:
    payload = b"\0".join(field.encode("utf-8") for field in fields) + b"\0"
    os.write(1, payload)


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--source", required=True)
    parser.add_argument("--repo-root", required=True)
    args = parser.parse_args()
    try:
        credentials = load_credentials(args.source, Path(args.repo_root))
    except CredentialError as exc:
        _emit_nul(["ERROR", str(exc)])
        return 1
    _emit_nul([
        "OK",
        credentials.source,
        credentials.host,
        str(credentials.port),
        credentials.username,
        credentials.password,
        str(credentials.tls).lower(),
        str(credentials.tls_insecure).lower(),
        credentials.ca_cert,
        credentials.vehicle_id,
    ])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
