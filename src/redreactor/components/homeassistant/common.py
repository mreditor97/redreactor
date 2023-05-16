"""Home Assistant Common."""

from json import JSONEncoder
from typing import Any


# Home Assistant MQTT Representer object
# Enabled the printing into a dict and to JSON
class Representer:
    """Representer.

    Enables printing into a dict and to JSON.
    """

    def __repr__(self) -> str:
        """Return Represent."""
        return repr({k: v for (k, v) in self.__dict__.items() if v is not None})


# Home Assistant MQTT JSON Encoder
# Allows the conversion of the Home Assistant objects to JSON
class Encoder(JSONEncoder):
    """Encoder.

    Allows the conversion of the Home Assistant object into JSON.
    """

    def default(self, o: Any) -> Any:
        """Encode object into JSON."""
        if isinstance(o, Device | Availability):
            return {k: v for (k, v) in o.__dict__.items() if v is not None}

        return JSONEncoder.default(self, o)


# Home Assistant MQTT Availability topic
# Topic to subscribe to receive availability updates
class Availability(Representer):
    """Availability.

    Adds Home Assistant MQTT Availability support.
    """

    topic: str
    payload_available: str | None
    payload_not_available: str | None

    def __init__(
        self,
        topic: str,
        payload_available: str | None = None,
        payload_not_available: str | None = None,
    ) -> None:
        """Initialise Home Assistant Availability object."""
        self.payload_available = payload_available
        self.payload_not_available = payload_not_available
        self.topic = topic


# Home Assistant MQTT Device
# Ties the device into the device registry within Home Assistant
class Device(Representer):
    """Device.

    Adds support for Home Assistant device list.
    """

    configuration_url: str | None
    connections: list[list[str]] | None  # [connection_type, connection_identifier]
    hw_version: str | None
    identifiers: str | list[str] | None
    manufacturer: str | None
    model: str | None
    name: str | None
    suggested_area: str | None
    sw_version: str | None
    via_device: str | None

    def __init__(  # noqa: PLR0913
        self,
        configuration_url: str | None = None,
        connections: list[list[str]] | None = None,
        hw_version: str | None = None,
        identifiers: str | list[str] | None = None,
        manufacturer: str | None = None,
        model: str | None = None,
        name: str | None = None,
        suggested_area: str | None = None,
        sw_version: str | None = None,
        via_device: str | None = None,
    ) -> None:
        """Initialise Home Assistant Device object."""
        self.configuration_url = configuration_url
        self.connections = connections
        self.hw_version = hw_version
        self.identifiers = identifiers
        self.manufacturer = manufacturer
        self.model = model
        self.name = name
        self.suggested_area = suggested_area
        self.sw_version = sw_version
        self.via_device = via_device


# Home Assistant MQTT Items
# Standard options available on all MQTT inputs
class Base(Representer):
    """Base.

    In all Home Assistant device types.
    """

    name: str | None
    device_class: str | None
    state_class: str | None
    entity_category: str | None
    expire_after: int | None  # Number of seconds after state becomes unavailable
    icon: str | None
    object_id: str | None
    unique_id: str | None
    state_topic: str | None
    value_template: str | None
    availability: list[Availability] | None
    availability_mode: str | None
    device: Device | None

    configuration_topic: str | None  # Used for one time creation of the Home Assistant configuration topic # noqa: E501

    def __init__(  # noqa: PLR0913
        self,
        name: str | None = None,
        device_class: str | None = None,
        state_class: str | None = None,
        entity_category: str | None = None,
        expire_after: int | None = None,
        icon: str | None = None,
        object_id: str | None = None,
        unique_id: str | None = None,
        state_topic: str | None = None,
        value_template: str | None = None,
        availability: list[Availability] | None = None,
        availability_mode: str | None = None,
        device: Device | None = None,
        configuration_topic: str | None = None,
    ) -> None:
        """Initialise Home Assistant Base object."""
        self.name = name
        self.device_class = device_class
        self.state_class = state_class
        self.entity_category = entity_category
        self.expire_after = expire_after
        self.icon = icon
        self.object_id = object_id
        self.unique_id = unique_id
        self.state_topic = state_topic
        self.value_template = value_template
        self.availability = availability
        self.availability_mode = availability_mode
        self.device = device

        self.configuration_topic = configuration_topic
