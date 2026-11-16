"""MQTT topics and payloads shared by the components."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Binary sensor payloads when a field doesn't configure its own
DEFAULT_PAYLOAD_ON = "ON"
DEFAULT_PAYLOAD_OFF = "OFF"


@dataclass(frozen=True)
class Topics:
    """The device's MQTT topics, built once from the static configuration.

    Every topic is `<base_topic>/<hostname>/<topic>`, and a command for a field
    is `<base_topic>/<hostname>/<set>/<field name>`.
    """

    device: str
    status: str
    state: str
    event: str
    set_prefix: str

    @classmethod
    def from_configuration(cls, static_configuration: dict[str, Any]) -> Topics:
        """Build the topics from the static configuration."""
        mqtt_configuration = static_configuration["mqtt"]
        topic = mqtt_configuration["topic"]
        device = "/".join(
            (
                str(mqtt_configuration["base_topic"]),
                str(static_configuration["hostname"]["name"]),
            ),
        )
        return cls(
            device=device,
            status=f"{device}/{topic['status']}",
            state=f"{device}/{topic['state']}",
            event=f"{device}/{topic['event']}",
            set_prefix=f"{device}/{topic['set']}/",
        )

    def command(self, field_name: str) -> str:
        """Return the topic a field's commands are received on."""
        return f"{self.set_prefix}{field_name}"


def binary_payload(field_configuration: dict[str, Any], value: bool) -> str:
    """Return a binary sensor field's payload for on or off."""
    if value:
        return str(field_configuration.get("payload_on", DEFAULT_PAYLOAD_ON))
    return str(field_configuration.get("payload_off", DEFAULT_PAYLOAD_OFF))
