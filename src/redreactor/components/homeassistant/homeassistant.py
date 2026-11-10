"""Home Assistant module."""

from __future__ import annotations

import json
import logging
import re
import threading
from importlib.metadata import version
from typing import TYPE_CHECKING, Any

from redreactor.components.mqtt import MQTT
from redreactor.const import (
    HOMEASSISTANT_EXPIRE_AFTER_MARGIN,
    HOMEASSISTANT_MIGRATION_DELAY,
    HOMEASSISTANT_ONLINE_STATE_DELAY,
)
from redreactor.helpers.repeater import RepeatTimer

from .binary_sensor import BinarySensor
from .button import Button
from .common import Availability, Base, Device, Encoder
from .event import Event
from .number import Number
from .sensor import Sensor

if TYPE_CHECKING:
    from paho.mqtt.client import Client, MQTTMessage

    from redreactor.configuration import DynamicConfiguration


# (entity type, field name) of entities earlier versions published that have
# since been removed, so they are deleted from Home Assistant
REMOVED_ENTITIES = (
    # Replaced by the under-voltage and throttled binary sensors
    ("sensor", "cpu_stat_raw"),
)


# Base attributes that aren't part of an entity's discovery configuration
COMPONENT_EXCLUDED_KEYS = frozenset({"configuration_topic", "device", "component_id"})


def _discovery_id(text: str) -> str:
    """Make text safe for a discovery topic level.

    Home Assistant ignores a discovery topic whose node or object ID has any
    character other than letters, digits, _ and -, so a hostname such as
    `pi.local` or `my pi` would never be discovered.
    """
    return re.sub(r"[^a-zA-Z0-9_-]", "_", text)


def _slugify(text: str) -> str:
    """Turn text into the lower case letters, digits and _ of an entity ID."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


class Homeassistant:
    """Home Assistant integration."""

    logger = logging.getLogger("Red Reactor")

    configuration: list[Sensor | Number | BinarySensor | Button | Event]

    # Shared by every entity, sent once at the top of the device discovery
    _device: Device
    _availability: list[Availability]
    _state_topic: str

    # Set once the old per-entity discovery topics have been migrated
    _migrated: bool = False

    _static_configuration: dict[str, Any] = {}
    _dynamic_configuration: DynamicConfiguration

    configuration_report_timer: RepeatTimer

    def __init__(
        self,
        static_configuration: dict[str, Any],
        dynamic_configuration: DynamicConfiguration,
    ) -> None:
        """Initialise Home Assistant integration object."""
        self._static_configuration = static_configuration
        self._dynamic_configuration = dynamic_configuration
        self.configuration = []
        self._migrated = False
        self._migration_lock = threading.Lock()
        self._online_lock = threading.Lock()
        self._online_timer: threading.Timer | None = None

        self._expire_after = self._effective_expire_after()
        self._process_homeassistant_configuration(static_configuration)

        # A new report interval can change the expire after time, which Home
        # Assistant only learns from the discovery message
        self._dynamic_configuration.event.on(
            event_name="write",
            function=self._dynamic_configuration_written,
        )

        # Register MQTT listeners
        MQTT.event.on(event_name="on_connect", function=self._mqtt_on_connect)
        MQTT.event.on(event_name="on_message", function=self._mqtt_on_message)

        # Push a configuration update at a repeated interval
        self.configuration_report_timer = RepeatTimer(
            float(self._static_configuration["homeassistant"]["discovery_interval"]),
            self._update_homeassistant_configuration,
        )

        self.logger.info("Home Assistant support has been enabled")

    def _process_homeassistant_configuration(self, static_configuration: Any) -> None:
        """Process Home Assistant configuration."""
        configuration_defaults: Device = Device(
            identifiers=f"redreactor_{static_configuration['hostname']['name']}",
            name=f"Red Reactor {static_configuration['hostname']['pretty']}",
            manufacturer="Pascal Herczog",
            model="Red Reactor",
            hw_version="Rev 1.5",
            sw_version=version("redreactor"),
        )
        self._device = configuration_defaults
        mqtt_configuration = static_configuration["mqtt"]
        topics = mqtt_configuration["topic"]
        hostname = static_configuration["hostname"]["name"]
        device_topic = f"{mqtt_configuration['base_topic']}/{hostname}"
        self._state_topic = f"{device_topic}/{topics['state']}"
        self._availability = [
            Availability(
                topic=f"{device_topic}/{topics['status']}",
                payload_available=f"{static_configuration['status']['online']}",
                payload_not_available=f"{static_configuration['status']['offline']}",
            ),
        ]

        for field_key in static_configuration["fields"]:
            field = static_configuration["fields"][field_key]

            configuring: Base = Base(
                name=f"{field.get('pretty')}",
                device_class=field.get("device_class", None),
                expire_after=self._expire_after,
                entity_category=field.get("entity_category", None),
                icon=field.get("icon", None),
                default_entity_id=self._default_entity_id(
                    field,
                    str(configuration_defaults.name),
                ),
                unique_id=f"{configuration_defaults.identifiers}_{field['name']}",
                # The legacy per-entity discovery topic, only used to migrate
                # Home Assistant to the device discovery that replaces it
                configuration_topic=f"{static_configuration['homeassistant']['topic']}/{field['type']}/{_discovery_id(str(configuration_defaults.identifiers))}_{field['name']}/config",
                availability_mode=f"{field.get('availability_mode', 'all')}",
                value_template=field.get(
                    "value_template",
                    f"{ '{{ value_json.' + str(field['name']) + ' }}' }",
                ),
                enabled_by_default=field.get("enabled_by_default", True),
            )

            configured: Sensor | BinarySensor | Number | Button | Event = Sensor()
            if field["type"] == "sensor":
                configured = Sensor(
                    unit_of_measurement=field.get("unit", None),
                    suggested_display_precision=field.get(
                        "suggested_display_precision",
                        None,
                    ),
                    state_class=field.get("state_class", "measurement"),
                )

            if field["type"] == "binary_sensor":
                configured = BinarySensor(
                    payload_on=field.get("payload_on", "ON"),
                    payload_off=field.get("payload_off", "OFF"),
                )

            if field["type"] == "number":
                configured = Number(
                    command_topic=f"{static_configuration['mqtt']['base_topic']}/{static_configuration['hostname']['name']}/{static_configuration['mqtt']['topic']['set']}/{field['name']}",
                    command_template=f"{ '{{ value }}' }",
                    min=field.get("min", 0),
                    max=field.get("max", 300),
                    mode=field.get("mode", "auto"),
                    step=field.get("step", 0.5),
                    optimistic=field.get("optimistic", None),
                    unit_of_measurement=field.get("unit", None),
                )

            if field["type"] == "event":
                configured = Event(
                    event_types=list(field.get("event_types", [])),
                )
                # Events have their own topic and payload, the JSON event is
                # read as it is, and they never expire
                configuring.state_topic = f"{device_topic}/{topics['event']}"
                configuring.value_template = field.get("value_template")
                configuring.expire_after = None

            if field["type"] == "button":
                configured = Button(
                    command_topic=f"{static_configuration['mqtt']['base_topic']}/{static_configuration['hostname']['name']}/{static_configuration['mqtt']['topic']['set']}/{field['name']}",
                    command_template=f"{ '{{ value }}' }",
                    payload_press=field.get(
                        "payload_press",
                        json.dumps(True),  # noqa: FBT003
                    ),
                )

            # Overlay the shared Base fields onto the type-specific object.
            # `configuring` (Base) wins on any key present in both, which is
            # intentional — Base carries the authoritative common attributes
            # such as unique_id, state_topic, and availability.
            configured.__dict__ |= configuring.__dict__

            # Not part of the entity's own configuration, they place it in the
            # device discovery message
            configured.platform = str(field["type"])
            configured.component_id = str(field["name"])

            self.configuration.append(configured)

    def _effective_expire_after(self) -> int:
        """Return the expire after time sent to Home Assistant, in seconds.

        Home Assistant marks an entity unavailable when no state arrives within
        `expire_after`. The report interval can be set up to 300 seconds from
        Home Assistant, longer than the default 120 second expire after, which
        would leave every entity unavailable between reports. So the time is
        raised to at least two report intervals plus a margin. 0 turns expiry
        off and is kept as it is.
        """
        configured = int(self._static_configuration["homeassistant"]["expire_after"])
        if configured == 0:
            return 0

        report_interval = int(self._dynamic_configuration.data["report_interval"])
        return max(
            configured,
            2 * report_interval + HOMEASSISTANT_EXPIRE_AFTER_MARGIN,
        )

    def _dynamic_configuration_written(self) -> None:
        """Republish discovery when the expire after time has changed."""
        expire_after = self._effective_expire_after()
        if expire_after == self._expire_after:
            return

        self.logger.info(
            "Report interval changed, Home Assistant expire after is now %is",
            expire_after,
        )
        self._expire_after = expire_after
        for entity in self.configuration:
            # Events never expire
            if entity.expire_after is not None:
                entity.expire_after = expire_after
        self._publish_device_discovery()

    def _default_entity_id(self, field: dict[str, Any], device_name: str) -> str:
        """Return the entity ID Home Assistant should create the entity with.

        Home Assistant deprecated `object_id` in favour of `default_entity_id`,
        which takes a full entity ID including the domain. An `object_id` from
        older configuration files is converted so it keeps working.

        Without either, the entity ID is the device name and the field name,
        such as `sensor.red_reactor_pi_voltage`. Home Assistant would otherwise
        make one up from the entity's name, which can include the device's
        area. It only applies when the entity is first created, so existing
        entity IDs, and any renamed in Home Assistant, are kept.
        """
        if field.get("default_entity_id"):
            return str(field["default_entity_id"])

        if field.get("object_id"):
            self.logger.warning(
                "The `object_id` option of the %s field is deprecated, "
                "use `default_entity_id: %s.%s` instead",
                field["name"],
                field["type"],
                field["object_id"],
            )
            return f"{field['type']}.{field['object_id']}"

        return f"{field['type']}.{_slugify(device_name)}_{_slugify(field['name'])}"

    @property
    def _device_discovery_topic(self) -> str:
        """Topic for the single device discovery message holding every entity."""
        homeassistant_topic = self._static_configuration["homeassistant"]["topic"]
        device_id = _discovery_id(str(self._device.identifiers))
        return f"{homeassistant_topic}/device/{device_id}/config"

    def _device_discovery_payload(self) -> dict[str, Any]:
        """Build the device discovery payload.

        The device, origin, availability and state topic are shared, so they
        are sent once instead of in every entity. An entity's own value, such
        as the event entity's state topic, takes precedence. None values are
        left out, Home Assistant rejects discovery payloads with null fields.
        """
        components: dict[str, Any] = {}
        for field in self.configuration:
            component = {
                k: v
                for (k, v) in field.__dict__.items()
                if v is not None and k not in COMPONENT_EXCLUDED_KEYS
            }
            if component.get("state_topic") == self._state_topic:
                del component["state_topic"]
            components[str(field.component_id)] = component

        return {
            "device": self._device,
            "origin": {
                "name": "redreactor",
                "sw_version": version("redreactor"),
                "support_url": "https://github.com/mreditor97/redreactor",
            },
            "availability": self._availability,
            "state_topic": self._state_topic,
            "components": components,
        }

    def _update_homeassistant_configuration(self) -> None:
        """Push Home Assistant configuration for auto discovery.

        The first time, the entities are first moved over from the older one
        message per entity discovery (see `_migrate_discovery`).
        """
        with self._migration_lock:
            migrate = not self._migrated
            self._migrated = True

        if migrate:
            self._migrate_discovery()
            return

        self._publish_device_discovery()

    def _publish_device_discovery(self) -> None:
        """Publish the device discovery message."""
        self.logger.debug(
            "Publishing Homeassistant MQTT configuration / discovery information",
        )

        MQTT.event.emit(
            event_name="publish",
            topic=self._device_discovery_topic,
            payload=json.dumps(self._device_discovery_payload(), cls=Encoder),
        )

    def _migrate_discovery(self) -> None:
        """Move Home Assistant from per-entity discovery to device discovery.

        Earlier versions published one discovery message per entity. Following
        Home Assistant's migration steps, each old topic is first sent
        `{"migrate_discovery": true}`, which unloads the entity but keeps its
        entity ID, name and history. The device discovery then picks the
        entities up again by their unique IDs, and the old topics are cleared
        with an empty retained message. Removed entities, such as the raw CPU
        stat sensor, are sent an empty message, which deletes them.

        Sent on every start, as Home Assistant may still have the old entities
        loaded. Where it doesn't, Home Assistant ignores these messages.
        """
        legacy_topics = [str(field.configuration_topic) for field in self.configuration]

        for topic in self._removed_entity_topics():
            MQTT.event.emit(event_name="publish", topic=topic, payload="")

        for topic in legacy_topics:
            MQTT.event.emit(
                event_name="publish",
                topic=topic,
                payload=json.dumps({"migrate_discovery": True}),
            )

        def finish() -> None:
            self._publish_device_discovery()
            for topic in legacy_topics:
                MQTT.event.emit(
                    event_name="publish",
                    topic=topic,
                    payload="",
                    retain=True,
                )

        # Give Home Assistant time to unload the old entities first, run off
        # the MQTT network thread so it isn't blocked while waiting
        timer = threading.Timer(HOMEASSISTANT_MIGRATION_DELAY, finish)
        timer.daemon = True
        timer.start()

    def _removed_entity_topics(self) -> list[str]:
        """Old discovery topics of entities that are no longer published."""
        homeassistant_topic = self._static_configuration["homeassistant"]["topic"]
        return [
            f"{homeassistant_topic}/{entity_type}/{_discovery_id(str(self._device.identifiers))}_{name}/config"
            for entity_type, name in REMOVED_ENTITIES
        ]

    @property
    def _status_topic(self) -> str:
        """Topic Home Assistant publishes its online / offline status to."""
        return str(self._static_configuration["homeassistant"]["status_topic"])

    @property
    def _status_online(self) -> str:
        """Payload Home Assistant publishes when it comes online."""
        return str(self._static_configuration["homeassistant"]["status_online"])

    def _mqtt_on_connect(
        self,
        client: Client,
        _userdata: Any,
        _flags: Any,
        _reason_code: Any,
        _properties: Any = None,
    ) -> None:
        """On MQTT Connect, publish Home Assistant configuration."""
        self._update_homeassistant_configuration()
        self.configuration_report_timer.start()
        # Home Assistant announces itself here when it (re)starts, so the
        # discovery configuration and latest readings can be sent again
        client.subscribe(topic=self._status_topic)

    def _mqtt_on_message(
        self,
        _client: Client,
        _userdata: Any,
        message: MQTTMessage,
    ) -> None:
        """Republish discovery and the latest readings when Home Assistant is online."""
        if (
            message.topic == self._status_topic
            and message.payload.decode("utf-8", errors="replace") == self._status_online
        ):
            # Anyone with access to the broker can publish here. A flood of
            # online messages would otherwise start a timer thread each, until
            # no more threads can be started, so one republish is queued at a
            # time.
            with self._online_lock:
                if self._online_timer is not None and self._online_timer.is_alive():
                    self.logger.debug(
                        "Home Assistant online again, a republish is already queued",
                    )
                    return
                timer = threading.Timer(
                    HOMEASSISTANT_ONLINE_STATE_DELAY,
                    MQTT.event.emit,
                    args=("homeassistant_online",),
                )
                timer.daemon = True
                self._online_timer = timer

            self.logger.info(
                "Home Assistant is online, publishing discovery and latest readings",
            )
            self._update_homeassistant_configuration()

            # The readings are retained, but they are sent again so Home
            # Assistant has fresh ones straight after it restarts. Wait briefly
            # so it has created the entities from the discovery message first.
            timer.start()
