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
    with (
        patch.object(homeassistant, "_update_homeassistant_configuration") as update,
        patch("redreactor.components.homeassistant.homeassistant.threading.Timer"),
    ):
        homeassistant._mqtt_on_message(
            None,
            None,
            _message("homeassistant/status", b"online"),
        )

    update.assert_called_once()


def test_birth_message_resends_latest_readings(homeassistant):
    """Home Assistant coming online asks for the latest readings after a delay."""
    from redreactor.components.mqtt import MQTT
    from redreactor.const import HOMEASSISTANT_ONLINE_STATE_DELAY

    with (
        patch.object(homeassistant, "_update_homeassistant_configuration"),
        patch(
            "redreactor.components.homeassistant.homeassistant.threading.Timer",
        ) as timer,
    ):
        homeassistant._mqtt_on_message(
            None,
            None,
            _message("homeassistant/status", b"online"),
        )

    timer.assert_called_once_with(
        HOMEASSISTANT_ONLINE_STATE_DELAY,
        MQTT.event.emit,
        args=("homeassistant_online",),
    )
    timer.return_value.start.assert_called_once()


def test_status_topic_and_payload_are_configurable(static_config, dynamic_config):
    """A custom birth topic and payload are subscribed to and matched."""
    from redreactor.components.homeassistant import Homeassistant

    static_config["homeassistant"]["status_topic"] = "ha/birth"
    static_config["homeassistant"]["status_online"] = "up"
    homeassistant = Homeassistant(static_config, dynamic_config)
    client = MagicMock()

    with (
        patch.object(homeassistant, "_update_homeassistant_configuration") as update,
        patch.object(homeassistant.configuration_report_timer, "start"),
        patch("redreactor.components.homeassistant.homeassistant.threading.Timer"),
    ):
        homeassistant._mqtt_on_connect(client, None, None, None)
        update.reset_mock()
        homeassistant._mqtt_on_message(None, None, _message("ha/birth", b"online"))
        update.assert_not_called()
        homeassistant._mqtt_on_message(None, None, _message("ha/birth", b"up"))
        update.assert_called_once()

    client.subscribe.assert_called_once_with(topic="ha/birth")


@pytest.mark.parametrize(
    ("topic", "payload"),
    [
        ("homeassistant/status", b"offline"),
        ("redreactor/redreactor/set/report_interval", b"online"),
    ],
)
def test_other_messages_do_not_republish_discovery(homeassistant, topic, payload):
    """Only Home Assistant's online birth message triggers discovery."""
    with (
        patch.object(homeassistant, "_update_homeassistant_configuration") as update,
        patch(
            "redreactor.components.homeassistant.homeassistant.threading.Timer",
        ) as timer,
    ):
        homeassistant._mqtt_on_message(None, None, _message(topic, payload))

    update.assert_not_called()
    timer.assert_not_called()


DEVICE_TOPIC = "homeassistant/device/redreactor_redreactor/config"


def _published(homeassistant, *, migrated=True):
    """Run a discovery update and return what was published, in order."""
    from redreactor.components.mqtt import MQTT

    published = []
    MQTT.event.on(
        "publish",
        lambda topic, payload, **kwargs: published.append((topic, payload, kwargs)),
    )
    homeassistant._migrated = migrated
    homeassistant._update_homeassistant_configuration()
    return published


def _device_payload(homeassistant):
    """Return the published device discovery payload."""
    import json

    published = _published(homeassistant)
    assert [topic for topic, _, _ in published] == [DEVICE_TOPIC]
    return json.loads(published[0][1])


def _components(homeassistant):
    """Return the entities of the device discovery payload by key."""
    return _device_payload(homeassistant)["components"]


def test_device_sw_version_is_package_version(homeassistant):
    """Discovery reports the installed redreactor version."""
    from importlib.metadata import version

    payload = _device_payload(homeassistant)

    assert payload["device"]["sw_version"] == version("redreactor")
    assert payload["origin"]["name"] == "redreactor"
    assert payload["origin"]["sw_version"] == version("redreactor")


def test_configuration_is_not_shared_between_instances(static_config, dynamic_config):
    """Each instance builds its own discovery list instead of appending to one."""
    from redreactor.components.homeassistant import Homeassistant

    first = Homeassistant(static_config, dynamic_config)
    second = Homeassistant(static_config, dynamic_config)

    assert len(first.configuration) == len(static_config["fields"])
    assert len(second.configuration) == len(static_config["fields"])


def test_device_discovery_shares_device_availability_and_state_topic(homeassistant):
    """Shared options are sent once, at the top of the device discovery."""
    payload = _device_payload(homeassistant)

    assert payload["device"]["identifiers"] == "redreactor_redreactor"
    assert payload["device"]["name"] == "Red Reactor Red Reactor"
    assert payload["state_topic"] == "redreactor/redreactor/state"
    assert payload["availability"] == [
        {
            "topic": "redreactor/redreactor/status",
            "payload_available": "online",
            "payload_not_available": "offline",
        },
    ]
    for key, component in payload["components"].items():
        assert "device" not in component, key
        assert "availability" not in component, key
        assert "configuration_topic" not in component, key
        assert "component_id" not in component, key
        assert None not in component.values(), key


def test_device_discovery_has_one_component_per_field(homeassistant, static_config):
    """Every field is an entity, keyed by its name, with its platform."""
    components = _components(homeassistant)

    assert set(components) == {
        field["name"] for field in static_config["fields"].values()
    }
    for field in static_config["fields"].values():
        component = components[field["name"]]
        assert component["platform"] == field["type"]
        assert component["unique_id"] == f"redreactor_redreactor_{field['name']}"


def test_discovery_includes_power_and_charging(homeassistant):
    """Power is a watt sensor and charging a battery_charging binary sensor."""
    components = _components(homeassistant)

    power = components["power"]
    assert power["device_class"] == "power"
    assert power["unit_of_measurement"] == "W"
    assert power["state_class"] == "measurement"

    charging = components["charging"]
    assert charging["device_class"] == "battery_charging"
    assert charging["entity_category"] == "diagnostic"
    assert charging["payload_on"] == "ON"
    assert charging["value_template"] == "{{ value_json.charging }}"


def test_discovery_includes_under_voltage_and_throttled(homeassistant):
    """Under-voltage and throttling are diagnostic problem binary sensors."""
    components = _components(homeassistant)

    for key in ("under_voltage", "throttled"):
        sensor = components[key]
        assert sensor["platform"] == "binary_sensor"
        assert sensor["device_class"] == "problem"
        assert sensor["entity_category"] == "diagnostic"
        assert sensor["value_template"] == f"{{{{ value_json.{key} }}}}"

    assert "cpu_stat_raw" not in components


def test_discovery_includes_power_event(homeassistant):
    """Power events are an event entity on their own topic, without expiry."""
    event = _components(homeassistant)["power_event"]

    assert event["platform"] == "event"
    assert event["state_topic"] == "redreactor/redreactor/event"
    assert event["event_types"] == [
        "power_lost",
        "power_restored",
        "low_battery",
        "shutdown_started",
    ]
    assert "value_template" not in event
    assert "expire_after" not in event


def test_discovery_sets_default_entity_id_from_device_and_field(homeassistant):
    """Without configuration the entity ID is the device name and field name."""
    components = _components(homeassistant)

    assert components["voltage"]["default_entity_id"] == (
        "sensor.red_reactor_red_reactor_voltage"
    )
    assert components["battery_warning_threshold"]["default_entity_id"] == (
        "number.red_reactor_red_reactor_battery_warning_threshold"
    )
    assert components["power_event"]["default_entity_id"] == (
        "event.red_reactor_red_reactor_power_event"
    )
    for component in components.values():
        assert "object_id" not in component


def test_default_entity_id_is_slugified(static_config, dynamic_config):
    """A device name with spaces and symbols makes a valid entity ID."""
    from redreactor.components.homeassistant import Homeassistant

    static_config["hostname"]["pretty"] = "Garage Pi #2"
    components = _components(Homeassistant(static_config, dynamic_config))

    assert components["voltage"]["default_entity_id"] == (
        "sensor.red_reactor_garage_pi_2_voltage"
    )


def test_default_entity_id_is_published(static_config, dynamic_config):
    """A configured default_entity_id is passed to Home Assistant."""
    from redreactor.components.homeassistant import Homeassistant

    static_config["fields"]["voltage"]["default_entity_id"] = "sensor.ups_voltage"
    components = _components(Homeassistant(static_config, dynamic_config))

    assert components["voltage"]["default_entity_id"] == "sensor.ups_voltage"


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
    external_power = _components(homeassistant)["external_power"]

    assert external_power["default_entity_id"] == "binary_sensor.ups_power"
    assert "object_id" not in external_power
    assert "deprecated" in caplog.text


def test_discovery_includes_battery_capacity(homeassistant):
    """The battery capacity is a number entity in mAh with a command topic."""
    capacity = _components(homeassistant)["battery_capacity"]

    assert capacity["command_topic"] == "redreactor/redreactor/set/battery_capacity"
    assert capacity["unit_of_measurement"] == "mAh"
    assert (capacity["min"], capacity["max"], capacity["step"]) == (0, 20000, 1)


def test_discovery_includes_battery_time_remaining(homeassistant):
    """The time remaining is a duration sensor in days."""
    remaining = _components(homeassistant)["battery_time_remaining"]

    assert remaining["unit_of_measurement"] == "d"
    assert remaining["device_class"] == "duration"
    assert remaining["value_template"] == "{{ value_json.battery_time_remaining }}"


def test_first_discovery_migrates_the_old_entity_topics(homeassistant, static_config):
    """The old per-entity topics are migrated before the device discovery."""
    import json

    with patch(
        "redreactor.components.homeassistant.homeassistant.threading.Timer",
    ) as timer:
        published = _published(homeassistant, migrated=False)

    legacy = [
        f"homeassistant/{field['type']}/redreactor_redreactor_{field['name']}/config"
        for field in static_config["fields"].values()
    ]
    removed = "homeassistant/sensor/redreactor_redreactor_cpu_stat_raw/config"

    # The removed raw CPU stat sensor is deleted, the rest are migrated
    assert published[0] == (removed, "", {})
    assert published[1:] == [
        (topic, json.dumps({"migrate_discovery": True}), {}) for topic in legacy
    ]
    assert homeassistant._migrated is True

    # After a delay the device discovery is sent and the old topics cleared
    delay, finish = timer.call_args.args
    from redreactor.const import HOMEASSISTANT_MIGRATION_DELAY

    assert delay == HOMEASSISTANT_MIGRATION_DELAY
    published.clear()
    finish()
    assert published[0][0] == DEVICE_TOPIC
    assert published[1:] == [(topic, "", {"retain": True}) for topic in legacy]


def test_migration_runs_only_once(homeassistant):
    """Later discovery updates only publish the device discovery."""
    with patch("redreactor.components.homeassistant.homeassistant.threading.Timer"):
        _published(homeassistant, migrated=False)

    published = _published(homeassistant, migrated=True)

    assert [topic for topic, _, _ in published] == [DEVICE_TOPIC]


def test_online_flood_queues_one_republish(homeassistant):
    """Repeated online messages start one timer, not one each.

    3000 online messages used to start 3000 timer threads at once.
    """
    timer_class = "redreactor.components.homeassistant.homeassistant.threading.Timer"
    with (
        patch.object(homeassistant, "_update_homeassistant_configuration") as update,
        patch(timer_class) as timer,
    ):
        timer.return_value.is_alive.return_value = True
        for _ in range(50):
            homeassistant._mqtt_on_message(
                None,
                None,
                _message("homeassistant/status", b"online"),
            )

    timer.assert_called_once()
    update.assert_called_once()


def test_online_after_the_queued_republish_runs_again(homeassistant):
    """Once the queued republish has run, the next online message is handled."""
    timer_class = "redreactor.components.homeassistant.homeassistant.threading.Timer"
    with (
        patch.object(homeassistant, "_update_homeassistant_configuration") as update,
        patch(timer_class) as timer,
    ):
        timer.return_value.is_alive.return_value = False
        for _ in range(2):
            homeassistant._mqtt_on_message(
                None,
                None,
                _message("homeassistant/status", b"online"),
            )

    assert timer.call_count == 2
    assert update.call_count == 2


@pytest.mark.parametrize(
    ("hostname", "device_id"),
    [
        ("pi", "redreactor_pi"),
        ("my pi", "redreactor_my_pi"),
        ("pi.local", "redreactor_pi_local"),
        ("pi-2_b", "redreactor_pi-2_b"),
    ],
)
def test_discovery_topic_is_valid_for_any_hostname(
    static_config,
    dynamic_config,
    hostname,
    device_id,
):
    """Home Assistant ignores discovery topics with other characters.

    A hostname of `pi.local` or `my pi` used to give no entities at all.
    """
    from redreactor.components.homeassistant import Homeassistant

    static_config["hostname"]["name"] = hostname
    homeassistant = Homeassistant(static_config, dynamic_config)

    assert (
        homeassistant._device_discovery_topic
        == f"homeassistant/device/{device_id}/config"
    )
    for topic in homeassistant._removed_entity_topics():
        assert topic.split("/")[2].startswith(device_id)


# ---------------------------------------------------------------------------
# Expire after follows the report interval
# ---------------------------------------------------------------------------


def test_expire_after_kept_when_longer_than_two_reports(homeassistant):
    """The default 30 second report interval keeps the configured 120 seconds."""
    assert _components(homeassistant)["voltage"]["expire_after"] == 120


def test_expire_after_raised_for_a_long_report_interval(
    static_config,
    dynamic_config,
):
    """A report interval above the expire after time no longer expires entities."""
    from redreactor.components.homeassistant import Homeassistant

    dynamic_config.data["report_interval"] = 300

    homeassistant = Homeassistant(static_config, dynamic_config)

    components = _components(homeassistant)
    assert components["voltage"]["expire_after"] == 630
    assert "expire_after" not in components["power_event"]


def test_expire_after_zero_is_kept(static_config, dynamic_config):
    """0 turns expiry off, whatever the report interval."""
    from redreactor.components.homeassistant import Homeassistant

    static_config["homeassistant"]["expire_after"] = 0
    dynamic_config.data["report_interval"] = 300

    homeassistant = Homeassistant(static_config, dynamic_config)

    assert _components(homeassistant)["voltage"]["expire_after"] == 0


@pytest.mark.usefixtures("homeassistant")
def test_report_interval_change_republishes_discovery(dynamic_config):
    """Changing the report interval from Home Assistant updates the expiry."""
    import json

    from redreactor.components.mqtt import MQTT

    published = []
    MQTT.event.on(
        "publish",
        lambda topic, payload, **_: published.append((topic, payload)),
    )

    dynamic_config.data["report_interval"] = 200
    dynamic_config.event.emit("write")

    discovery = [payload for topic, payload in published if topic == DEVICE_TOPIC]
    assert len(discovery) == 1
    components = json.loads(discovery[0])["components"]
    assert components["voltage"]["expire_after"] == 430
    assert "expire_after" not in components["power_event"]


@pytest.mark.usefixtures("homeassistant")
def test_unrelated_setting_change_does_not_republish(dynamic_config):
    """A change that keeps the expiry the same sends no discovery."""
    from redreactor.components.mqtt import MQTT

    published = []
    MQTT.event.on("publish", lambda topic, **_: published.append(topic))

    dynamic_config.data["battery_capacity"] = 3500
    dynamic_config.event.emit("write")

    assert DEVICE_TOPIC not in published


# ---------------------------------------------------------------------------
# Fewer discovery messages
# ---------------------------------------------------------------------------


def test_discovery_interval_zero_does_not_repeat(static_config, dynamic_config):
    """0 sends discovery on connect only, without the repeat timer."""
    from redreactor.components.homeassistant import Homeassistant

    static_config["homeassistant"]["discovery_interval"] = 0
    homeassistant = Homeassistant(static_config, dynamic_config)

    with (
        patch.object(homeassistant, "_update_homeassistant_configuration") as update,
        patch.object(homeassistant.configuration_report_timer, "start") as start,
    ):
        homeassistant._mqtt_on_connect(MagicMock(), None, None, None)

    update.assert_called_once()
    start.assert_not_called()


def test_discovery_json_is_built_once(homeassistant):
    """The unchanged discovery payload isn't rebuilt for every publish."""
    first = _published(homeassistant)[0][1]
    with patch.object(homeassistant, "_device_discovery_payload") as build:
        second = _published(homeassistant)[0][1]

    build.assert_not_called()
    assert second == first


def test_finished_migration_is_saved(homeassistant, dynamic_config):
    """Once migrated, the dynamic configuration records it."""
    import json
    from pathlib import Path

    with patch(
        "redreactor.components.homeassistant.homeassistant.threading.Timer",
    ) as timer:
        _published(homeassistant, migrated=False)
    _, finish = timer.call_args.args
    finish()

    saved = json.loads(Path(dynamic_config._dynamic_file).read_text())
    assert saved["discovery_migration"] == 1


def test_saved_migration_is_not_repeated(static_config, dynamic_config):
    """A restart after the migration sends only the device discovery."""
    from redreactor.components.homeassistant import Homeassistant
    from redreactor.components.mqtt import MQTT

    dynamic_config.data["discovery_migration"] = 1
    homeassistant = Homeassistant(static_config, dynamic_config)

    published = []
    MQTT.event.on("publish", lambda topic, **_: published.append(topic))
    homeassistant._update_homeassistant_configuration()

    assert published == [DEVICE_TOPIC]


def test_discovery_includes_the_new_entities(homeassistant):
    """The sensor problem, last shutdown, refresh and readings settings."""
    components = homeassistant._device_discovery_payload()["components"]

    assert components["sensor_problem"]["platform"] == "binary_sensor"
    assert components["sensor_problem"]["device_class"] == "problem"
    assert components["last_shutdown"]["platform"] == "sensor"
    assert "state_class" not in components["last_shutdown"]
    assert components["last_shutdown_time"]["device_class"] == "timestamp"
    assert components["last_shutdown_voltage"]["unit_of_measurement"] == "V"
    assert components["refresh"]["platform"] == "button"
    assert components["refresh"]["command_topic"] == "redreactor/redreactor/set/refresh"
    for name in ("monitor_interval", "average_readings", "shutdown_readings"):
        assert components[name]["platform"] == "number"
        assert components[name]["command_topic"].endswith(f"/set/{name}")
