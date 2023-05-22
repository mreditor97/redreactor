"""Home Assistant module."""
import json
import logging
from typing import Any

from paho.mqtt.client import Client

from redreactor.components.mqtt import MQTT
from redreactor.configuration import DynamicConfiguration
from redreactor.helpers.repeater import RepeatTimer

from .binary_sensor import BinarySensor
from .button import Button
from .common import Availability, Base, Device, Encoder
from .number import Number
from .sensor import Sensor


class Homeassistant:
    """Home Assistant integration."""

    logger = logging.getLogger("Red Reactor")

    configuration: list[Sensor | Number | BinarySensor | Button] = []

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

        self._process_homeassistant_configuration(static_configuration)

        # Register MQTT listeners
        MQTT.event.on(event_name="on_connect", function=self._mqtt_on_connect)

        # Register Dynamic Configuration update listener
        self._dynamic_configuration.event.on(
            event_name="write",
            function=self._update_homeassistant_timer,
        )

        # Push a configuration update at a repeated interval
        self.configuration_report_timer = RepeatTimer(
            float(
                self._dynamic_configuration.data[
                    self._static_configuration["fields"]["report_interval"]["name"]
                ],
            )
            * 4,
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
            sw_version="1.0.0",
        )

        for field in static_configuration["fields"]:
            field = static_configuration["fields"][field]  # noqa: PLW2901

            configuring: Base = Base(
                name=f"{configuration_defaults.name} {field.get('pretty')}",
                device_class=field.get("device_class", None),
                state_class="measurement",
                expire_after=int(static_configuration["homeassistant"]["expire_after"]),
                entity_category=field.get("entity_category", None),
                icon=field.get("icon", None),
                object_id=field.get("object_id", None),
                unique_id=f"{configuration_defaults.identifiers}_{field['name']}",
                state_topic=f"{static_configuration['mqtt']['base_topic']}/{static_configuration['hostname']['name']}/{static_configuration['mqtt']['topic']['state']}",
                configuration_topic=f"{static_configuration['homeassistant']['topic']}/{field['type']}/{configuration_defaults.identifiers}_{field['name']}/config",
                availability=[
                    Availability(
                        topic=f"{static_configuration['mqtt']['base_topic']}/{static_configuration['hostname']['name']}/{static_configuration['mqtt']['topic']['status']}",
                        payload_available=f"{static_configuration['status']['online']}",
                        payload_not_available=f"{static_configuration['status']['offline']}",
                    ),
                ],
                availability_mode=f"{field.get('availability_mode', 'all')}",
                value_template=field.get(
                    "value_template",
                    f"{ '{{ value_json.' + str(field['name']) + ' }}' }",
                ),
                device=configuration_defaults,
            )

            configured: Sensor | BinarySensor | Number | Button = Sensor()
            if field["type"] == "sensor":
                configured = Sensor(
                    unit_of_measurement=field.get("unit", None),
                    suggested_display_precision=field.get(
                        "suggested_display_precision",
                        None,
                    ),
                    state_class=field.get("state_class", None),
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

            if field["type"] == "button":
                configured = Button(
                    command_topic=f"{static_configuration['mqtt']['base_topic']}/{static_configuration['hostname']['name']}/{static_configuration['mqtt']['topic']['set']}/{field['name']}",
                    command_template=f"{ '{{ value }}' }",
                    payload_press=field.get(
                        "payload_press",
                        json.dumps(True),  # noqa: FBT003
                    ),
                )

            # Merge the configurations
            configured.__dict__ |= configuring.__dict__

            # Append the configuration to the configuration variable
            self.configuration.append(configured)

    def _update_homeassistant_configuration(self) -> None:
        """Push Home Assistant configuration for auto discovery."""
        self.logger.debug(
            "Publishing Homeassistant MQTT configuration / discovery information",
        )

        # Publish Home Assistant configuration for each field
        for field in self.configuration:
            MQTT.event.emit(
                event_name="publish",
                topic=field.configuration_topic,
                payload=json.dumps(
                    {k: v for (k, v) in field.__dict__.items() if v is not None},
                    cls=Encoder,
                ),
            )

    def _update_homeassistant_timer(self) -> None:
        """Update Home Assistant configuration update timer."""
        # Update configuration report interval timer
        self.configuration_report_timer.interval = float(
            self._static_configuration["homeassistant"]["discovery_interval"],
        )

    def _mqtt_on_connect(  # noqa: PLR0913
        self,
        client: Client,  # noqa: ARG002
        userdata: Any,  # noqa: ARG002
        flags: Any,  # noqa: ARG002
        rc: Any,  # noqa: ARG002
        reasoncode: Any = None,  # noqa: ARG002
    ) -> None:
        """On MQTT Connect, publish Home Assistant configuration."""
        self._update_homeassistant_configuration()
        self.configuration_report_timer.start()
