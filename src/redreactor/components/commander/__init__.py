"""Commander module.

Adds support for receiving and processing MQTT commands.
"""
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Any, Literal

from paho.mqtt.client import Client, MQTTMessage

from redreactor.components.monitor import Monitor
from redreactor.components.mqtt import MQTT
from redreactor.configuration import DynamicConfiguration
from redreactor.helpers.emitter import EventEmitter


class Commander:
    """Commander for processing received MQTT commands."""

    logger = logging.getLogger("Red Reactor")

    event: EventEmitter = EventEmitter()

    _static_configuration: dict[str, Any] = {}
    _dynamic_configuration: DynamicConfiguration
    _monitor: Monitor

    def __init__(
        self,
        static_configuration: dict[str, Any],
        dynamic_configuration: DynamicConfiguration,
        monitor: Monitor,
    ) -> None:
        """Initialise the Commander object."""
        self._static_configuration = static_configuration
        self._dynamic_configuration = dynamic_configuration
        self._monitor = monitor

        self.logger.debug("Setup the command handler")

        # Register Shutdown event listener
        self._monitor.event.on(event_name="shutdown", function=self._shutdown)

        # Register MQTT events
        MQTT.event.on(event_name="on_connect", function=self._on_connect)
        MQTT.event.on(event_name="on_message", function=self._on_message)

    def _on_connect(  # noqa: PLR0913
        self,
        client: Client,
        userdata: Any,  # noqa: ARG002
        flags: Any,  # noqa: ARG002
        rc: Any,  # noqa: ARG002
        reasoncode: Any = None,  # noqa: ARG002
    ) -> None:
        """Process Commander subscriptions on MQTT connect event."""
        # Loop through all available field options
        for field in self._static_configuration["fields"]:
            # Only process fields that are of type button or number
            if self._static_configuration["fields"][field]["type"] in {
                "number",
                "button",
            }:
                self.logger.info(
                    "Subscribing to the %s topic at: %s/%s/%s/%s",
                    field,
                    self._static_configuration["mqtt"]["base_topic"],
                    self._static_configuration["hostname"]["name"],
                    self._static_configuration["mqtt"]["topic"]["set"],
                    self._static_configuration["fields"][field]["pretty"],
                )

                # Subscribe to that specific topic
                client.subscribe(
                    topic=f"{self._static_configuration['mqtt']['base_topic']}/{self._static_configuration['hostname']['name']}/{self._static_configuration['mqtt']['topic']['set']}/{self._static_configuration['fields'][field]['name']}",
                )

    def _on_message(
        self,
        client_id: str,  # noqa: ARG002
        userdata: Any,  # noqa: ARG002
        message: MQTTMessage,
    ) -> None:
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
                "JSON Decode Error: %s",
                str(message.payload.decode("utf-8")),
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
                    "%s button has been pressed",
                    self._static_configuration["fields"][field]["pretty"],
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
                    "%s update command received, changing to value %s",
                    self._static_configuration["fields"][field]["pretty"],
                    command,
                )

                # Update Dynamic configuration with latest value
                self._dynamic_configuration.data[field] = command

                # Dynamic configuration has changed, call write event
                self._dynamic_configuration.event.emit("write")
                return

        # If it gets to here, the received command is invalid
        self.logger.warning("Command received on %s is invalid", topic)

    def _on_command(self, event_type: Literal["shutdown", "restart"]) -> None:
        """Commander's on command event.

        Must contain an event_type of 'shutdown' or 'restart'.
        """
        # Check to ensure that the event_type is either shutdown or restart
        if event_type not in {"shutdown", "restart"}:
            msg = "Invalid device command."
            raise ValueError(msg)

        self.logger.info(
            "Device %s has been called. Last running at %s",
            event_type,
            datetime.now().strftime("%H:%M:%S"),  # noqa: DTZ005
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
        os.system(self._static_configuration["system"][event_type])  # noqa: S605

        # Exit the program
        sys.exit(0)

    def _shutdown(self) -> None:
        """Shutdown event hook."""
        self._on_command(event_type="shutdown")
