import json
import logging
import os
import time

from typing import Any, Literal
from datetime import datetime
from paho.mqtt.client import Client

from configuration import DynamicConfiguration
from monitor.monitor import Monitor
from events.emitter import EventEmitter
from mqtt.mqtt import MQTT, MQTTMessage


class Commander:
    logger = logging.getLogger("Red Reactor")

    event: EventEmitter = EventEmitter()

    _static_configuration: dict[str, Any] = dict()
    _dynamic_configuration: DynamicConfiguration
    _monitor: Monitor

    def __init__(
        self,
        static_configuration: dict[str, Any],
        dynamic_configuration: DynamicConfiguration,
        monitor: Monitor,
    ):
        self._static_configuration = static_configuration
        self._dynamic_configuration = dynamic_configuration
        self._monitor = monitor

        self.logger.debug("Setup the command handler")

        # Register Shutdown event listener
        self._monitor.event.on(event_name="shutdown", function=self._shutdown)

        # Register MQTT events
        MQTT.event.on(event_name="on_connect", function=self._on_connect)
        MQTT.event.on(event_name="on_message", function=self._on_message)

    def _on_connect(self, client: Client, userdata, flags, rc, reasonCode=None):
        """Process Commander subscriptions on MQTT connect event."""

        # Loop through all available field options
        for field in self._static_configuration["fields"]:
            # Only process fields that are of type button or number
            if self._static_configuration["fields"][field]["type"] in {
                "number",
                "button",
            }:
                self.logger.info(
                    f"Subscribing to the {field} topic at: {self._static_configuration['mqtt']['base_topic']}/{self._static_configuration['hostname']['name']}/{self._static_configuration['mqtt']['topic']['set']}/{self._static_configuration['fields'][field]['name']}"
                )

                # Subscribe to that specific topic
                client.subscribe(
                    topic=f"{self._static_configuration['mqtt']['base_topic']}/{self._static_configuration['hostname']['name']}/{self._static_configuration['mqtt']['topic']['set']}/{self._static_configuration['fields'][field]['name']}"
                )

    def _on_message(self, client_id: str, userdata, message: MQTTMessage):
        """Process Commander messages on MQTT message event."""

        # Remove the start of the topic to leave the command
        topic = str(message.topic).replace(
            f"{self._static_configuration['mqtt']['base_topic']}/{self._static_configuration['hostname']['name']}/{self._static_configuration['mqtt']['topic']['set']}/",
            "",
        )

        # Convert the received command into readable JSON
        try:
            command = json.loads(str(message.payload.decode("utf-8")))
        except json.JSONDecodeError:
            self.logger.warning(
                f"JSON Decode Error: {str(message.payload.decode('utf-8'))}"
            )
            return

        # Loop through available fields to find the expected command topic
        for field in self._static_configuration["fields"]:
            # If the received command is of type button
            if (
                self._static_configuration["fields"][field]["type"]
                in {
                    "button",
                }
                and field in topic
            ):
                self.logger.info(
                    f"{self._static_configuration['fields'][field]['pretty']} button has been pressed"
                )
                self._on_command(event_type=field)
                return

            # If the received command is of type number
            if (
                self._static_configuration["fields"][field]["type"]
                in {
                    "number",
                }
                and field in topic
            ):
                self.logger.info(
                    f"{self._static_configuration['fields'][field]['pretty']} update command received, changing to value {command}"
                )

                # Update Dynamic configuration with latest value
                self._dynamic_configuration.data[field] = command

                # Dynamic configuration has changed, call write event
                self._dynamic_configuration.event.emit("write")
                return

        # If it gets to here, the received command is invalid
        self.logger.warning(f"Command received on {topic} is invalid")

    def _on_command(self, event_type: Literal["shutdown", "restart"]):
        """Commander's on command event, must contain a event_type of 'shutdown' or 'restart'"""

        # Check to ensure that the event_type is either shutdown or restart
        assert event_type in {"shutdown", "restart"}, "Invalid device command"

        self.logger.info(
            f"Device {event_type} has been called. Last running at {datetime.now().strftime('%H:%M:%S')}"
        )

        # Publish to MQTT the offline state, before shutting down or restarting
        MQTT.event.emit(
            event_name="publish",
            topic=f"{self._static_configuration['mqtt']['base_topic']}/{self._static_configuration['hostname']['name']}/{self._static_configuration['mqtt']['topic']['status']}",
            payload=f"{self._static_configuration['status']['offline']}",
        )

        # Ensure the MQTT data has been published to the broker
        time.sleep(2)

        # Initiate event type (shutdown or restart)
        os.system(self._static_configuration["system"][event_type])

        # Exit the program
        exit(0)

    def _shutdown(self):
        """Shutdown event hook"""
        self._on_command(event_type="shutdown")
