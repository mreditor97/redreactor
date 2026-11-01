"""Commander module.

Adds support for receiving and processing MQTT commands.
"""

from __future__ import annotations

import json
import logging
import math
import shlex
import subprocess
import threading
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from redreactor.components.mqtt import MQTT
from redreactor.const import DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP
from redreactor.helpers.emitter import EventEmitter

if TYPE_CHECKING:
    from paho.mqtt.client import Client, MQTTMessage

    from redreactor.components.monitor import Monitor
    from redreactor.configuration import DynamicConfiguration


class Commander:
    """Commander for processing received MQTT commands."""

    logger = logging.getLogger("Red Reactor")

    event: EventEmitter

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
        self.event = EventEmitter()
        self._static_configuration = static_configuration
        self._dynamic_configuration = dynamic_configuration
        self._monitor = monitor

        self.logger.debug("Setup the command handler")

        # Register Shutdown event listener
        self._monitor.event.on(event_name="shutdown", function=self._shutdown)

        # Register MQTT events
        MQTT.event.on(event_name="on_connect", function=self._on_connect)
        MQTT.event.on(event_name="on_message", function=self._on_message)

    def _on_connect(
        self,
        client: Client,
        _userdata: Any,
        _flags: Any,
        _reason_code: Any,
        _properties: Any = None,
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
                    self._static_configuration["fields"][field]["pretty"],
                    self._static_configuration["mqtt"]["base_topic"],
                    self._static_configuration["hostname"]["name"],
                    self._static_configuration["mqtt"]["topic"]["set"],
                    self._static_configuration["fields"][field]["name"],
                )

                # Subscribe to that specific topic
                client.subscribe(
                    topic=f"{self._static_configuration['mqtt']['base_topic']}/{self._static_configuration['hostname']['name']}/{self._static_configuration['mqtt']['topic']['set']}/{self._static_configuration['fields'][field]['name']}",
                )

    def _on_message(
        self,
        _client: Client,
        _userdata: Any,
        message: MQTTMessage,
    ) -> None:
        """Process Commander messages on MQTT message event."""
        prefix = "/".join(
            (
                self._static_configuration["mqtt"]["base_topic"],
                self._static_configuration["hostname"]["name"],
                self._static_configuration["mqtt"]["topic"]["set"],
                "",
            ),
        )

        # Other components subscribe to their own topics, which are not
        # commands for us
        if not str(message.topic).startswith(prefix):
            return

        # Remove the start of the topic to leave the command
        topic = str(message.topic).removeprefix(prefix)

        # Convert the received command into readable JSON. Anyone with access
        # to the broker can publish here, and an exception raised inside a paho
        # callback stops the MQTT loop, so a bad payload must only be logged.
        try:
            command = json.loads(message.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.logger.warning(
                "Command received on %s is not valid JSON: %r",
                topic,
                message.payload,
            )
            return

        # Loop through available fields to find the expected command topic
        for field in self._static_configuration["fields"]:
            # If the received command is of type button
            if (
                self._static_configuration["fields"][field]["type"]
                == "button"
                and topic == self._static_configuration["fields"][field]["name"]
            ):
                self.logger.info(
                    "%s button has been pressed",
                    self._static_configuration["fields"][field]["pretty"],
                )
                # Run off the MQTT network thread: publishes made from inside a
                # paho callback are only queued, and sleeping here would block
                # the loop that has to deliver the offline status.
                threading.Thread(
                    target=self._on_command,
                    kwargs={"event_type": field},
                    name=f"redreactor-{field}",
                ).start()
                return

            # If the received command is of type number
            if (
                self._static_configuration["fields"][field]["type"]
                == "number"
                and topic == self._static_configuration["fields"][field]["name"]
            ):
                self.logger.info(
                    "%s update command received, changing to value %s",
                    self._static_configuration["fields"][field]["pretty"],
                    command,
                )

                if not self._is_valid_number(field, command):
                    return

                # Update Dynamic configuration with latest value
                self._dynamic_configuration.data[field] = command

                # Dynamic configuration has changed, call write event
                self._dynamic_configuration.event.emit("write")
                return

        # If it gets to here, the received command is invalid
        self.logger.warning("Command received on %s is invalid", topic)

    def _is_valid_number(self, field: str, value: Any) -> bool:
        """Check a received number command before it is persisted.

        Values are written to the dynamic configuration file and read back with
        int()/float() on every monitor tick, so anything that is not a finite
        number inside the field's range would break the service on every start.
        """
        field_configuration = self._static_configuration["fields"][field]

        # bool is a subclass of int, but `true` is never a meaningful setting
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            self.logger.warning(
                "Ignoring %s update, %r is not a number",
                field_configuration["pretty"],
                value,
            )
            return False

        minimum = field_configuration.get("min")
        maximum = field_configuration.get("max")
        if (minimum is not None and value < minimum) or (
            maximum is not None and value > maximum
        ):
            self.logger.warning(
                "Ignoring %s update, %s is outside the range %s to %s",
                field_configuration["pretty"],
                value,
                minimum,
                maximum,
            )
            return False

        # The battery level is scaled between the two voltages, so an inverted
        # pair would stop the battery from ever reading 0% (and shutting down).
        if field in {"battery_voltage_minimum", "battery_voltage_maximum"}:
            voltage_minimum = float(
                value
                if field == "battery_voltage_minimum"
                else self._dynamic_configuration.data["battery_voltage_minimum"],
            )
            voltage_maximum = float(
                value
                if field == "battery_voltage_maximum"
                else self._dynamic_configuration.data["battery_voltage_maximum"],
            )
            if (
                voltage_minimum
                >= voltage_maximum - DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP
            ):
                self.logger.warning(
                    "Ignoring %s update, battery voltage minimum (%sV) must be "
                    "below the maximum (%sV) by more than %sV",
                    field_configuration["pretty"],
                    voltage_minimum,
                    voltage_maximum,
                    DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP,
                )
                return False

        return True

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
            datetime.now(tz=UTC).strftime("%H:%M:%S"),
        )

        # Publish to MQTT the offline state, before shutting down or restarting
        MQTT.event.emit(
            event_name="publish",
            topic=f"{self._static_configuration['mqtt']['base_topic']}/{self._static_configuration['hostname']['name']}/{self._static_configuration['mqtt']['topic']['status']}",
            payload=f"{self._static_configuration['status']['offline']}",
            qos=1,
            retain=True,
        )

        # Give the broker time to deliver the offline status before the TCP
        # connection drops when the process exits.
        time.sleep(2)

        # The shutdown/restart command comes from the trusted YAML config, not
        # from the MQTT payload, so splitting with shlex (shell=False) is safe.
        cmd = shlex.split(self._static_configuration["system"][event_type])
        try:
            result = subprocess.run(cmd, check=False)  # noqa: S603
        except OSError:
            self.logger.exception("Unable to run the %s command %s", event_type, cmd)
        else:
            if result.returncode != 0:
                self.logger.error(
                    "The %s command %s failed with exit code %i",
                    event_type,
                    cmd,
                    result.returncode,
                )

        # This runs on a worker or timer thread, where sys.exit() would only end
        # that thread. Disconnecting makes loop_forever() return in the main
        # thread, which then exits the program.
        MQTT.event.emit(event_name="disconnect")

    def _shutdown(self) -> None:
        """Shutdown event hook."""
        self._on_command(event_type="shutdown")
