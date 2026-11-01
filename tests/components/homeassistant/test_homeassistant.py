"""Tests for the Home Assistant component."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from redreactor.helpers.emitter import EventEmitter


@pytest.fixture(autouse=True)
def reset_mqtt_events():
    """Reset the class-level MQTT EventEmitter before and after each test."""
    from redreactor.components.mqtt import MQTT

    MQTT.event = EventEmitter()
    yield
    MQTT.event = EventEmitter()


@pytest.fixture
def homeassistant(static_config, dynamic_config):
    """Return a Homeassistant instance."""
    from redreactor.components.homeassistant import Homeassistant

    return Homeassistant(static_config, dynamic_config)


def _message(topic: str, payload: bytes) -> MagicMock:
    message = MagicMock()
    message.topic = topic
    message.payload = payload
    return message


def test_discovery_timer_uses_discovery_interval(static_config, dynamic_config):
    """The discovery timer runs at discovery_interval from the start."""
    from redreactor.components.homeassistant import Homeassistant

    static_config["homeassistant"]["discovery_interval"] = 600

    homeassistant = Homeassistant(static_config, dynamic_config)

    assert homeassistant.configuration_report_timer.interval == 600


def test_on_connect_subscribes_to_birth_topic(homeassistant):
    """Connecting subscribes to Home Assistant's birth message topic."""
    client = MagicMock()

    with (
        patch.object(homeassistant, "_update_homeassistant_configuration"),
        patch.object(homeassistant.configuration_report_timer, "start"),
    ):
        homeassistant._mqtt_on_connect(client, None, None, None)

    client.subscribe.assert_called_once_with(topic="homeassistant/status")


def test_birth_message_republishes_discovery(homeassistant):
    """Home Assistant coming online triggers an immediate discovery publish."""
    with patch.object(homeassistant, "_update_homeassistant_configuration") as update:
        homeassistant._mqtt_on_message(
            None,
            None,
            _message("homeassistant/status", b"online"),
        )

    update.assert_called_once()


@pytest.mark.parametrize(
    ("topic", "payload"),
    [
        ("homeassistant/status", b"offline"),
        ("redreactor/redreactor/set/report_interval", b"online"),
    ],
)
def test_other_messages_do_not_republish_discovery(homeassistant, topic, payload):
    """Only Home Assistant's online birth message triggers discovery."""
    with patch.object(homeassistant, "_update_homeassistant_configuration") as update:
        homeassistant._mqtt_on_message(None, None, _message(topic, payload))

    update.assert_not_called()
