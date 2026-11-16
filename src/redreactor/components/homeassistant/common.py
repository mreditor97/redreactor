"""Home Assistant Common."""

from __future__ import annotations

from dataclasses import dataclass, fields
from json import JSONEncoder
from typing import Any


@dataclass(kw_only=True, repr=False)
class Representer:
    """A Home Assistant MQTT discovery object.

    Values left as None are not part of the discovery message, as Home
    Assistant rejects discovery payloads with null fields.
    """

    def as_dict(self) -> dict[str, Any]:
        """Return the values that are set, by their discovery name."""
        return {
            field.name: value
            for field in fields(self)
            if (value := getattr(self, field.name)) is not None
        }

    def __repr__(self) -> str:
        """Return the values that are set."""
        return repr(self.as_dict())


class Encoder(JSONEncoder):
    """Encode the Home Assistant discovery objects into JSON."""

    def default(self, o: Any) -> Any:
        """Encode object into JSON."""
        if isinstance(o, Representer):
            return o.as_dict()

        return JSONEncoder.default(self, o)


@dataclass(kw_only=True, repr=False)
class Availability(Representer):
    """Topic Home Assistant reads the device's availability from."""

    topic: str
    payload_available: str | None = None
    payload_not_available: str | None = None


@dataclass(kw_only=True, repr=False)
class Device(Representer):
    """Ties the entities to one device in Home Assistant's device registry."""

    configuration_url: str | None = None
    connections: list[list[str]] | None = None  # [connection_type, identifier]
    hw_version: str | None = None
    identifiers: str | list[str] | None = None
    manufacturer: str | None = None
    model: str | None = None
    name: str | None = None
    suggested_area: str | None = None
    sw_version: str | None = None
    via_device: str | None = None


@dataclass(kw_only=True, repr=False)
class Base(Representer):
    """Options every Home Assistant MQTT entity type has."""

    name: str | None = None
    device_class: str | None = None
    entity_category: str | None = None
    expire_after: int | None = None  # Seconds until the state is unavailable
    icon: str | None = None
    default_entity_id: str | None = None
    unique_id: str | None = None
    state_topic: str | None = None
    value_template: str | None = None
    availability: list[Availability] | None = None
    availability_mode: str | None = None
    device: Device | None = None
    enabled_by_default: bool | None = None

    configuration_topic: str | None = None  # The legacy per-entity topic
    platform: str | None = None  # The entity type in the device discovery
    component_id: str | None = None  # The entity's key in the device discovery
