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
from redreactor.const import (
    COMMAND_PAYLOAD_MAXIMUM,
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP,
    POWER_EVENT_SHUTDOWN_STARTED,
    SYSTEM_COMMAND_TIMEOUT,
)
from redreactor.helpers.emitter import EventEmitter
from redreactor.helpers.topics import Topics

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
        self._topics = Topics.from_configuration(static_configuration)
        # The button and number fields, by the name they are commanded with.
        # Built once, so a message is routed with one lookup
        self._commands: dict[str, str] = {
            str(field["name"]): key
            for key, field in static_configuration["fields"].items()
            if field["type"] in {"number", "button"}
        }
        # Held from the first shutdown or restart until the program exits, so
        # a repeated low battery reading or button press doesn't run it twice
        self._command_lock = threading.Lock()

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
        for name, key in self._commands.items():
            topic = self._topics.command(name)
            self.logger.info(
                "Subscribing to the %s topic at: %s",
                self._static_configuration["fields"][key]["pretty"],
                topic,
            )
            client.subscribe(topic=topic)

    def _on_message(
        self,
        _client: Client,
        _userdata: Any,
        message: MQTTMessage,
    ) -> None:
        """Process Commander messages on MQTT message event."""
        prefix = self._topics.set_prefix

        # Other components subscribe to their own topics, which are not
        # commands for us
        if not str(message.topic).startswith(prefix):
            return

        # Remove the start of the topic to leave the command
        topic = str(message.topic).removeprefix(prefix)

        # Convert the received command into readable JSON. Anyone with access
        # to the broker can publish here, and an exception raised inside a paho
        # callback stops the MQTT loop, so a bad payload must only be logged.
        # A setting is a single number, so a large payload is never a valid
        # command. Refusing it first also stops a deeply nested JSON payload
        # from raising RecursionError while it is decoded.
        if len(message.payload) > COMMAND_PAYLOAD_MAXIMUM:
            self.logger.warning(
                "Command received on %s is too large (%i bytes), ignoring it",
                topic,
                len(message.payload),
            )
            return
        try:
            command = json.loads(message.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            self.logger.warning(
                "Command received on %s is not valid JSON: %r",
                topic,
                message.payload,
            )
            return

        field = self._commands.get(topic)
        if field is None:
            self.logger.warning("Command received on %s is invalid", topic)
            return

        field_configuration = self._static_configuration["fields"][field]
        if field_configuration["type"] == "button":
            self.logger.info(
                "%s button has been pressed",
                field_configuration["pretty"],
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

        self.logger.info(
            "%s update command received, changing to value %s",
            field_configuration["pretty"],
            command,
        )

        if not self._is_valid_number(field, command):
            return

        # Update Dynamic configuration with latest value
        self._dynamic_configuration.data[field] = command

        # Dynamic configuration has changed, call write event
        self._dynamic_configuration.event.emit("write")

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
                (
                    value
                    if field == "battery_voltage_minimum"
                    else self._dynamic_configuration.data["battery_voltage_minimum"]
                ),
            )
            voltage_maximum = float(
                (
                    value
                    if field == "battery_voltage_maximum"
                    else self._dynamic_configuration.data["battery_voltage_maximum"]
                ),
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

        if not self._command_lock.acquire(blocking=False):
            self.logger.info("Device %s ignored, already shutting down", event_type)
            return

        self.logger.info(
            "Device %s has been called. Last running at %s",
            event_type,
            datetime.now(tz=UTC).strftime("%H:%M:%S"),
        )

        if event_type == "shutdown":
            # Lets Home Assistant automations react before the device goes
            # offline, whether a low battery or the button started it
            self._monitor.publish_event(POWER_EVENT_SHUTDOWN_STARTED)

        # Stop the readings, so nothing publishes online after the offline below
        self._monitor.stop()

        # Publish to MQTT the offline state, before shutting down or restarting
        MQTT.event.emit(
            event_name="publish",
            topic=self._topics.status,
            payload=f"{self._static_configuration['status']['offline']}",
            qos=1,
            retain=True,
        )

        # Give the broker time to deliver the offline status before the TCP
        # connection drops when the process exits.
        time.sleep(2)

        # The shutdown/restart command comes from the trusted YAML config, not
        # from the MQTT payload, so splitting with shlex (shell=False) is safe.
        # The commands are checked when the configuration is loaded, but this
        # must still reach the disconnect below if one can't be run, otherwise
        # the service is left running with the readings already stopped.
        command = self._static_configuration["system"][event_type]
        try:
            cmd = shlex.split(command)
            result = subprocess.run(  # noqa: S603
                cmd,
                check=False,
                timeout=SYSTEM_COMMAND_TIMEOUT,
            )
        except (OSError, ValueError):
            self.logger.exception(
                "Unable to run the %s command %r",
                event_type,
                command,
            )
        except subprocess.TimeoutExpired:
            self.logger.error(  # noqa: TRY400
                "The %s command %r did not finish within %i seconds",
                event_type,
                command,
                SYSTEM_COMMAND_TIMEOUT,
            )
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
