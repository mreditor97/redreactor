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


def test_device_sw_version_is_package_version(homeassistant):
    """Discovery reports the installed redreactor version."""
    from importlib.metadata import version

    assert homeassistant.configuration[0].device.sw_version == version("redreactor")


def test_configuration_is_not_shared_between_instances(static_config, dynamic_config):
    """Each instance builds its own discovery list instead of appending to one."""
    from redreactor.components.homeassistant import Homeassistant

    first = Homeassistant(static_config, dynamic_config)
    second = Homeassistant(static_config, dynamic_config)

    assert len(first.configuration) == len(static_config["fields"])
    assert len(second.configuration) == len(static_config["fields"])


def _discovery_payloads(homeassistant):
    """Return the published discovery payloads keyed by topic."""
    import json

    from redreactor.components.mqtt import MQTT

    published = {}
    MQTT.event.on(
        "publish",
        lambda topic, payload, **_: published.__setitem__(topic, json.loads(payload)),
    )
    homeassistant._update_homeassistant_configuration()
    return published


def test_discovery_includes_power_and_charging(homeassistant):
    """Power is a watt sensor and charging a battery_charging binary sensor."""
    published = _discovery_payloads(homeassistant)

    power = published["homeassistant/sensor/redreactor_redreactor_power/config"]
    assert power["device_class"] == "power"
    assert power["unit_of_measurement"] == "W"
    assert power["state_class"] == "measurement"

    charging = published[
        "homeassistant/binary_sensor/redreactor_redreactor_charging/config"
    ]
    assert charging["device_class"] == "battery_charging"
    assert charging["payload_on"] == "ON"
    assert charging["value_template"] == "{{ value_json.charging }}"


def test_discovery_includes_battery_runtime_limit(homeassistant):
    """The runtime limit is a number entity in minutes with a command topic."""
    published = _discovery_payloads(homeassistant)

    limit = published[
        "homeassistant/number/redreactor_redreactor_battery_runtime_limit/config"
    ]
    assert limit["command_topic"] == "redreactor/redreactor/set/battery_runtime_limit"
    assert limit["unit_of_measurement"] == "min"
    assert limit["device_class"] == "duration"
    assert (limit["min"], limit["max"], limit["step"]) == (0, 1440, 1)


def test_cpu_stat_raw_has_no_state_class(homeassistant):
    """A bitmask should not get long-term statistics."""
    published = _discovery_payloads(homeassistant)

    raw = published["homeassistant/sensor/redreactor_redreactor_cpu_stat_raw/config"]
    assert "state_class" not in raw


def test_discovery_omits_entity_id_by_default(homeassistant):
    """Without configuration Home Assistant picks the entity ID itself."""
    published = _discovery_payloads(homeassistant)

    for payload in published.values():
        assert "object_id" not in payload
        assert "default_entity_id" not in payload


def test_default_entity_id_is_published(static_config, dynamic_config):
    """A configured default_entity_id is passed to Home Assistant."""
    from redreactor.components.homeassistant import Homeassistant

    static_config["fields"]["voltage"]["default_entity_id"] = "sensor.ups_voltage"
    published = _discovery_payloads(Homeassistant(static_config, dynamic_config))

    voltage = published["homeassistant/sensor/redreactor_redreactor_voltage/config"]
    assert voltage["default_entity_id"] == "sensor.ups_voltage"


def test_object_id_is_converted_to_default_entity_id(
    static_config,
    dynamic_config,
    caplog,
):
    """The deprecated object_id still works, with the domain added."""
    from redreactor.components.homeassistant import Homeassistant

    static_config["fields"]["external_power"]["object_id"] = "ups_power"
    with caplog.at_level("WARNING", "Red Reactor"):
        homeassistant = Homeassistant(static_config, dynamic_config)
    published = _discovery_payloads(homeassistant)

    external_power = published[
        "homeassistant/binary_sensor/redreactor_redreactor_external_power/config"
    ]
    assert external_power["default_entity_id"] == "binary_sensor.ups_power"
    assert "object_id" not in external_power
    assert "deprecated" in caplog.text


def test_discovery_includes_battery_capacity(homeassistant):
    """The battery capacity is a number entity in mAh with a command topic."""
    published = _discovery_payloads(homeassistant)

    capacity = published[
        "homeassistant/number/redreactor_redreactor_battery_capacity/config"
    ]
    assert capacity["command_topic"] == "redreactor/redreactor/set/battery_capacity"
    assert capacity["unit_of_measurement"] == "mAh"
    assert (capacity["min"], capacity["max"], capacity["step"]) == (0, 20000, 1)


def test_discovery_includes_battery_time_remaining(homeassistant):
    """The time remaining is a duration sensor in minutes."""
    published = _discovery_payloads(homeassistant)

    remaining = published[
        "homeassistant/sensor/redreactor_redreactor_battery_time_remaining/config"
    ]
    assert remaining["unit_of_measurement"] == "min"
    assert remaining["device_class"] == "duration"
    assert remaining["value_template"] == "{{ value_json.battery_time_remaining }}"

