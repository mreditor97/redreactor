"""MQTT module.

Provides the connection and events around MQTT.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from paho.mqtt.client import Client, MQTTMessage, MQTTv5, MQTTv311

from redreactor.helpers.emitter import EventEmitter


class MQTT:
    """MQTT module."""

    logger = logging.getLogger("Red Reactor")

    # Class-level EventEmitter is intentional: it acts as a singleton event bus
    # so Monitor, Commander, and Homeassistant can all subscribe to the same
    # MQTT events without holding a direct reference to the MQTT instance.
    event: EventEmitter = EventEmitter()

    # MQTT Client
    _client: Client

    # Static file configuration
    _static_configuration: dict[str, Any] = {}

    # Exit on fail (stops if it cannot connect to the MQTT Broker)
    _exit_on_fail: bool = False

    def __init__(
        self,
        static_configuration: Any,
        exit_on_fail: bool = False,  # noqa: FBT001, FBT002
    ) -> None:
        """Initialise MQTT object."""
        self._static_configuration = static_configuration
        self._exit_on_fail = exit_on_fail

        self.event.on(event_name="publish", function=self.mqtt_publish)
        self.event.on(event_name="disconnect", function=self.disconnect)

        self.logger.info(
            "Configuring MQTT connection to: %s:%i",
            static_configuration["mqtt"]["broker"],
            static_configuration["mqtt"]["port"],
        )
        self.logger.debug(
            "Using MQTT Version %s, Protocol: %s",
            static_configuration["mqtt"]["version"],
            static_configuration["mqtt"]["transport"],
        )
        self.logger.debug(
            "MQTT `Exit on Fail` is %s",
            ("disabled", "enabled")[self._exit_on_fail],
        )

        try:
            # Check to see if the MQTT Version being used is MQTT V5
            if int(static_configuration["mqtt"]["version"]) == 5:
                self._client = Client(
                    client_id=static_configuration["mqtt"]["client_id"],
                    protocol=MQTTv5,
                    transport=static_configuration["mqtt"]["transport"],
                )

            # Check to see if the MQTT Version being used is MQTT V3.11
            if int(static_configuration["mqtt"]["version"]) == 3:
                self._client = Client(
                    client_id=static_configuration["mqtt"]["client_id"],
                    protocol=MQTTv311,
                    clean_session=True,
                    transport=static_configuration["mqtt"]["transport"],
                )
        except (ValueError, AttributeError):
            self.logger.exception("MQTT Client Error")

            if self._exit_on_fail:
                sys.exit(1)
        except NameError:
            self.logger.exception(
                "MQTT Client Version number is invalid, must be `3` or `5`",
            )

            if self._exit_on_fail:
                sys.exit(1)

        self._client.on_connect = self._mqtt_on_connect
        self._client.on_disconnect = self._mqtt_on_disconnect
        self._client.on_message = self._mqtt_on_message

        self._client.username_pw_set(
            static_configuration["mqtt"]["user"],
            static_configuration["mqtt"]["password"],
        )

        # The Last Will is sent inside the CONNECT packet, so it must be set
        # before connect() for it to cover the first session too. paho keeps it
        # for every automatic reconnect after that.
        self._client.will_set(
            topic=self._status_topic,
            payload=f"{static_configuration['status']['offline']}",
            qos=1,
            retain=True,
        )

    @property
    def _status_topic(self) -> str:
        """Topic used for the online / offline status."""
        mqtt_configuration = self._static_configuration["mqtt"]
        return "/".join(
            (
                mqtt_configuration["base_topic"],
                self._static_configuration["hostname"]["name"],
                mqtt_configuration["topic"]["status"],
            ),
        )

    def connect(
        self,
        broker: str = "127.0.0.1",
        port: int = 1883,
        timeout: int = 60,
    ) -> None:
        """MQTT Connect to the Broker."""
        self.logger.debug("Initiating connection to Broker: %s:%i", broker, port)

        try:
            self._client.connect(host=broker, port=port, keepalive=timeout)
        except OSError:
            # OSError covers refused connections, timeouts, DNS failures and an
            # unreachable network (common while a Pi is still booting).
            self.logger.exception("Unable to connect to the MQTT Broker")

            if self._exit_on_fail:
                # Non-zero so a supervisor (systemd Restart=on-failure) retries
                sys.exit(1)

        # Run forever until battery shutdown or user exit. Without
        # retry_first_connection, paho re-raises a failed first connection here
        # instead of retrying it.
        self._client.loop_forever(retry_first_connection=not self._exit_on_fail)

    def _mqtt_on_connect(
        self,
        client: Client,
        userdata: Any,
        flags: Any,
        rc: Any,
        reasoncode: Any = None,
    ) -> None:
        """MQTT Connect event."""
        if rc == 0:
            self.logger.info("Connected to MQTT Broker")

            # Replace any retained Last Will `offline` straight away, rather
            # than waiting for the first report
            self.mqtt_publish(
                topic=self._status_topic,
                payload=f"{self._static_configuration['status']['online']}",
                qos=1,
                retain=True,
            )

            # Notify MQTT event on_connect listeners. Arguments are passed
            # positionally because listeners name them differently (e.g.
            # `_client`), so keyword arguments would raise a TypeError.
            self.event.emit(
                "on_connect",
                client,
                userdata,
                flags,
                rc,
                reasoncode,
            )
        else:
            self.logger.error("MQTT Broker connection refused, error code %i", rc)

    def _mqtt_on_disconnect(
        self,
        client: Client,
        userdata: Any,
        rc: Any,
        reasoncode: Any = None,
    ) -> None:
        """MQTT Disconnect event."""
        self.logger.debug("Notifying listeners of client disconnect")

        self.event.emit(
            "on_disconnect",
            client,
            userdata,
            rc,
            reasoncode,
        )

        self.logger.info("Disconnected from broker")

    def _mqtt_on_message(
        self,
        client: Client,
        userdata: Any,
        message: MQTTMessage,
    ) -> None:
        """MQTT On Message event."""
        self.logger.debug(
            "Message received: %s - %s",
            str(message.topic),
            str(message.payload.decode("utf-8")),
        )

        self.event.emit(
            "on_message",
            client,
            userdata,
            message,
        )

    def mqtt_publish(
        self,
        topic: str,
        payload: str,
        qos: int = 0,
        retain: bool = False,  # noqa: FBT001, FBT002
    ) -> None:
        """Publish data to a MQTT Topic.

        Used to publish data on a specified MQTT topic, with a specified payload.
        """
        self.logger.debug("Publishing: %s - %s", topic, payload)

        self._client.publish(topic=topic, payload=payload, qos=qos, retain=retain)

    def disconnect(self) -> None:
        """Disconnect from the broker, which ends loop_forever()."""
        self.logger.info("Disconnecting from the MQTT Broker")

        self._client.disconnect()
