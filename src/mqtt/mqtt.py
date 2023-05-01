import logging
import socket
import sys

from typing import Any
from paho.mqtt.client import Client, MQTTv5, MQTTv311, MQTTMessage

from events.emitter import EventEmitter


class MQTT:
    logger = logging.getLogger("Red Reactor")

    event: EventEmitter = EventEmitter()

    # MQTT Client
    _client: Client

    # Static file configuration
    _static_configuration: dict[str, Any] = dict()

    # Exit on fail (stops if it cannot connect to the MQTT Broker)
    _exit_on_fail: bool = False

    def __init__(self, static_configuration, exit_on_fail: bool = False):
        self._static_configuration = static_configuration
        self._exit_on_fail = exit_on_fail

        self.event.on(event_name="publish", function=self.mqtt_publish)

        self.logger.info(
            f"Configuring MQTT connection to: {static_configuration['mqtt']['broker']}:{static_configuration['mqtt']['port']}"
        )
        self.logger.debug(
            f"Using MQTT Version {static_configuration['mqtt']['version']}, Protocol: {static_configuration['mqtt']['transport']}"
        )
        self.logger.debug(
            f"MQTT `Exit on Fail` is { ('disabled', 'enabled')[self._exit_on_fail] }"
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
        except (ValueError, AttributeError) as error:
            self.logger.error(f"MQTT Client Error: {error}")

            if self._exit_on_fail:
                sys.exit()
        except NameError:
            self.logger.error(
                f"MQTT Client Version number is invalid, must be `3` or `5`"
            )

            if self._exit_on_fail:
                sys.exit(0)

        self._client.on_connect = self._mqtt_on_connect
        self._client.on_disconnect = self._mqtt_on_disconnect
        self._client.on_message = self._mqtt_on_message

        self._client.username_pw_set(
            static_configuration["mqtt"]["user"],
            static_configuration["mqtt"]["password"],
        )

    def connect(self, broker: str = "127.0.0.1", port: int = 1883, timeout: int = 60):
        """MQTT Connect to the Broker"""
        self.logger.debug(f"Initiating connection to Broker: {broker}:{port}")

        try:
            self._client.connect(host=broker, port=port, keepalive=timeout)
        except (ConnectionRefusedError, socket.timeout) as error:
            self.logger.error(f"Unable to connect to the MQTT Broker: {error}")

            if self._exit_on_fail:
                sys.exit(0)

        # Run forever until battery shutdown or user exit
        self._client.loop_forever()

    def _mqtt_on_connect(self, client: Client, userdata, flags, rc, reasonCode=None):
        if rc == 0:
            self.logger.info(f"Connected to MQTT Broker")

            # Configure a last will message if something happens to the connection
            client.will_set(
                topic=f"{self._static_configuration['mqtt']['base_topic']}/{self._static_configuration['hostname']['name']}/{self._static_configuration['mqtt']['topic']['status']}",
                payload=f"{self._static_configuration['status']['offline']}",
                qos=1,
                retain=True,
            )

            # Notify MQTT event on_connect listeners
            self.event.emit(
                event_name="on_connect",
                client=client,
                userdata=userdata,
                flags=flags,
                rc=rc,
                reasonCode=reasonCode,
            )
        else:
            self.logger.error(f"MQTT Broker connection refused, error code {rc}")

    def _mqtt_on_disconnect(self, client: Client, userdata, rc, reasonCode=None):
        self.logger.debug("Notifying listeners of client disconnect")

        self.event.emit(
            event_name="on_disconnect",
            client=client,
            userdata=userdata,
            rc=rc,
            reasonCode=reasonCode,
        )

        self.logger.info("Disconnected from broker")

    def _mqtt_on_message(self, client_id: str, userdata, message: MQTTMessage):
        self.logger.debug(
            f"Message received: {str(message.topic)} - {str(message.payload.decode('utf-8'))}"
        )

        self.event.emit(
            event_name="on_message",
            client_id=client_id,
            userdata=userdata,
            message=message,
        )

    def mqtt_publish(self, topic, payload):
        self.logger.debug(f"Publishing: {topic} - {payload}")

        self._client.publish(topic=topic, payload=payload)
