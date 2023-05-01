import logging
import json

from typing import Any
from paho.mqtt.client import Client

from configuration import DynamicConfiguration
from events.repeater import RepeatTimer
from mqtt.mqtt import MQTT

from .number import Number
from .sensor import Sensor
from .binary_sensor import BinarySensor
from .button import Button
from .common import Device, Availability, Base, Encoder


class Homeassistant:
    logger = logging.getLogger("Red Reactor")

    configuration: list[Sensor | Number | BinarySensor] = list()

    _static_configuration: dict[str, Any] = dict()
    _dynamic_configuration: DynamicConfiguration

    configuration_report_timer: RepeatTimer

    def __init__(
        self,
        static_configuration: dict[str, Any],
        dynamic_configuration: DynamicConfiguration,
    ):
        self._static_configuration = static_configuration
        self._dynamic_configuration = dynamic_configuration

        self._process_homeassistant_configuration(static_configuration)

        # Register MQTT listeners
        MQTT.event.on(event_name="on_connect", function=self._mqtt_on_connect)

        # Register Dynamic Configuration update listener
        self._dynamic_configuration.event.on(
            event_name="write", function=self._update_homeassistant_timer
        )

        # Push a configuration update at a repeated interval
        self.configuration_report_timer = RepeatTimer(
            float(
                self._dynamic_configuration.data[
                    self._static_configuration["fields"]["report_interval"]["name"]
                ]
            )
            * 4,
            self._update_homeassistant_configuration,
        )

        self.logger.info("Home Assistant support has been enabled")

    def _process_homeassistant_configuration(self, static_configuration):
        configuration_defaults: Device = Device(
            identifiers=f"redreactor_{static_configuration['hostname']['name']}",
            name=f"Red Reactor {static_configuration['hostname']['pretty']}",
            manufacturer="Pascal Herczog",
            model="Red Reactor",
            hw_version="Rev 1.5",
            sw_version="1.0.0",
        )

        for field in static_configuration["fields"].keys():
            field = static_configuration["fields"][field]

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
                availability=list(
                    [
                        Availability(
                            topic=f"{static_configuration['mqtt']['base_topic']}/{static_configuration['hostname']['name']}/{static_configuration['mqtt']['topic']['status']}",
                            payload_available=f"{static_configuration['status']['online']}",
                            payload_not_available=f"{static_configuration['status']['offline']}",
                        )
                    ]
                ),
                availability_mode=f"{field.get('availability_mode', 'all')}",
                value_template=field.get(
                    "value_template",
                    f"{ str('{{ value_json.') + str(field['name']) + str(' }}') }",
                ),
                device=configuration_defaults,
            )

            configured: Sensor | BinarySensor | Number | Button | None = None
            if field["type"] == "sensor":
                configured: Sensor = Sensor(
                    unit_of_measurement=field.get("unit", None),
                    suggested_display_precision=field.get(
                        "suggested_display_precision", None
                    ),
                    state_class=field.get("state_class", None),
                )

            if field["type"] == "binary_sensor":
                configured: BinarySensor = BinarySensor(
                    payload_on=field.get("payload_on", "ON"),
                    payload_off=field.get("payload_off", "OFF"),
                )

            if field["type"] == "number":
                configured: Number = Number(
                    command_topic=f"{static_configuration['mqtt']['base_topic']}/{static_configuration['hostname']['name']}/{static_configuration['mqtt']['topic']['set']}/{field['name']}",
                    command_template=f"{ str('{{ value }}') }",
                    min=field.get("min", 0),
                    max=field.get("max", 300),
                    mode=field.get("mode", "auto"),
                    step=field.get("step", 0.5),
                    optimistic=field.get("optimistic", None),
                    unit_of_measurement=field.get("unit", None),
                )

                # self.logger.info(configured.command_template)

            if field["type"] == "button":
                configured: Button = Button(
                    command_topic=f"{static_configuration['mqtt']['base_topic']}/{static_configuration['hostname']['name']}/{static_configuration['mqtt']['topic']['set']}/{field['name']}",
                    command_template=f"{ str('{{ value }}') }",
                    payload_press=field.get("payload_press", json.dumps(True)),
                )

            # Merge the configurations
            configured.__dict__.update(configuring.__dict__)

            # Append the configuration to the configuration variable
            self.configuration.append(configured)

    def _update_homeassistant_configuration(self):
        """Push Home Assistant configuration for auto discovery"""

        self.logger.info(
            "Publishing Homeassistant MQTT configuration / discovery information"
        )

        # Publish Home Assistant configuration for each field
        for field in self.configuration:
            MQTT.event.emit(
                event_name="publish",
                topic=field.configuration_topic,
                payload=json.dumps(
                    dict({k: v for (k, v) in field.__dict__.items() if v is not None}),
                    cls=Encoder,
                ),
            )

    def _update_homeassistant_timer(self):
        """Update Home Assistant configuration update timer"""

        # Update configuration report interval timer
        self.configuration_report_timer.interval = float(
            self._static_configuration["homeassistant"]["discovery_interval"]
        )

    def _mqtt_on_connect(self, client: Client, userdata, flags, rc, reasonCode=None):
        """On MQTT Connect, publish Home Assistant configuration"""

        self._update_homeassistant_configuration()
        self.configuration_report_timer.start()
