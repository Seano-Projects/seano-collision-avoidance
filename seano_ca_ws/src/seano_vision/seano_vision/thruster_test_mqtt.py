"""Credential-safe paho wrapper shared by adapter and emergency guardian."""

from __future__ import annotations

import os


class PahoSharedTopicTransport:
    def __init__(self, *, client_id: str, topic: str, qos: int,
                 on_message, on_connection, on_ack) -> None:
        import paho.mqtt.client as mqtt

        try:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=client_id)
        except (AttributeError, TypeError):
            self.client = mqtt.Client(client_id=client_id)
        username = os.environ.get("SEANO_MQTT_USERNAME", "")
        password = os.environ.get("SEANO_MQTT_PASSWORD", "")
        if username or password:
            self.client.username_pw_set(username, password)
        ca_cert = os.environ.get("SEANO_MQTT_CA_CERT", "")
        client_cert = os.environ.get("SEANO_MQTT_CLIENT_CERT", "")
        client_key = os.environ.get("SEANO_MQTT_CLIENT_KEY", "")
        tls_enabled = os.environ.get("SEANO_MQTT_TLS", "").lower() == "true"
        tls_insecure = os.environ.get("SEANO_MQTT_TLS_INSECURE", "").lower() == "true"
        if not tls_enabled:
            raise RuntimeError("MQTT_TLS_REQUIRED")
        if tls_insecure:
            raise RuntimeError("MQTT_TLS_INSECURE_REJECTED")
        self.client.tls_set(
            ca_certs=ca_cert or None,
            certfile=client_cert or None,
            keyfile=client_key or None,
        )
        self.client.tls_insecure_set(False)
        self.topic = topic
        self.qos = int(qos)
        self.connected = False
        self._on_message_external = on_message
        self._on_connection_external = on_connection
        self._on_ack_external = on_ack
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.on_publish = self._on_publish

    def _on_connect(self, client, userdata, flags, rc, *extra):
        self.connected = int(rc) == 0
        if self.connected:
            client.subscribe(self.topic, qos=self.qos)
        self._on_connection_external(self.connected)

    def _on_disconnect(self, client, userdata, rc, *extra):
        self.connected = False
        self._on_connection_external(False)

    def _on_message(self, client, userdata, message):
        self._on_message_external(
            bytes(message.payload),
            bool(getattr(message, "retain", False)),
            int(getattr(message, "qos", 0)),
        )

    def _on_publish(self, client, userdata, mid, *extra):
        self._on_ack_external(int(mid))

    @staticmethod
    def _credentials() -> tuple[str, int]:
        host = os.environ.get("SEANO_MQTT_HOST", "")
        port_raw = os.environ.get("SEANO_MQTT_PORT", "1883")
        if not host:
            raise RuntimeError("SEANO_MQTT_HOST is required")
        return host, int(port_raw)

    def start(self) -> None:
        host, port = self._credentials()
        self.client.connect_async(host, port, keepalive=10)
        self.client.loop_start()

    def publish(self, topic: str, payload: str, qos: int, retain: bool):
        if retain:
            raise ValueError("retained publish is forbidden")
        if not self.connected:
            raise ConnectionError("MQTT disconnected")
        return self.client.publish(topic, payload, qos=int(qos), retain=False)

    def stop(self) -> None:
        try:
            self.client.disconnect()
        finally:
            self.client.loop_stop()
