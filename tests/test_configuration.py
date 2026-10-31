"""Tests for configuration module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from redreactor.configuration import (
    ConfigurationError,
    DynamicConfiguration,
    LinkedConfiguration,
)
from redreactor.const import (
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
    DEFAULT_BATTERY_VOLTAGE_MINIMUM,
    DEFAULT_BATTERY_WARNING_THRESHOLD,
    DEFAULT_REPORT_INTERVAL,
)

# ---------------------------------------------------------------------------
# DynamicConfiguration
# ---------------------------------------------------------------------------


def test_dynamic_config_creates_file_if_not_exists(tmp_path):
    """DynamicConfiguration creates the file with defaults when it doesn't exist."""
    dynamic_file = str(tmp_path / "dynamic.json")
    config = DynamicConfiguration(dynamic_file=dynamic_file)

    assert (tmp_path / "dynamic.json").exists()
    assert config.data["report_interval"] == DEFAULT_REPORT_INTERVAL
    assert config.data["battery_warning_threshold"] == DEFAULT_BATTERY_WARNING_THRESHOLD
    assert config.data["battery_voltage_minimum"] == DEFAULT_BATTERY_VOLTAGE_MINIMUM
    assert config.data["battery_voltage_maximum"] == DEFAULT_BATTERY_VOLTAGE_MAXIMUM


def test_dynamic_config_loads_existing_file_with_custom_values(tmp_path):
    """DynamicConfiguration loads custom values from an existing file."""
    dynamic_file = tmp_path / "dynamic.json"
    custom = {
        "report_interval": 60,
        "battery_warning_threshold": 20,
        "battery_voltage_minimum": 3.0,
        "battery_voltage_maximum": 4.1,
    }
    dynamic_file.write_text(json.dumps(custom))

    config = DynamicConfiguration(dynamic_file=str(dynamic_file))

    assert config.data["report_interval"] == 60
    assert config.data["battery_warning_threshold"] == 20


def test_dynamic_config_write_persists_data(tmp_path):
    """DynamicConfiguration.write() saves current data to the file."""
    dynamic_file = str(tmp_path / "dynamic.json")
    config = DynamicConfiguration(dynamic_file=dynamic_file)

    config.data["report_interval"] = 999
    config.write()

    with Path(dynamic_file).open() as f:
        saved = json.load(f)

    assert saved["report_interval"] == 999


# ---------------------------------------------------------------------------
# LinkedConfiguration
# ---------------------------------------------------------------------------


def test_linked_config_loads_yaml_static_file(tmp_path):
    """LinkedConfiguration loads and merges a YAML static config file."""
    static_file = tmp_path / "config.yaml"
    static_file.write_text(yaml.dump({"mqtt": {"broker": "192.168.1.1"}}))
    dynamic_file = str(tmp_path / "dynamic.json")

    linked = LinkedConfiguration(
        static_file=str(static_file),
        dynamic_file=dynamic_file,
    )

    assert linked.static["mqtt"]["broker"] == "192.168.1.1"


def test_linked_config_merges_over_defaults(tmp_path):
    """LinkedConfiguration merges static file values over defaults."""
    static_file = tmp_path / "config.yaml"
    static_file.write_text(yaml.dump({"mqtt": {"port": 1884}}))
    dynamic_file = str(tmp_path / "dynamic.json")

    linked = LinkedConfiguration(
        static_file=str(static_file),
        dynamic_file=dynamic_file,
    )

    # Custom port from file
    assert linked.static["mqtt"]["port"] == 1884
    # Default broker preserved
    assert linked.static["mqtt"]["broker"] == "127.0.0.1"


def test_linked_config_creates_dynamic_configuration(tmp_path):
    """LinkedConfiguration creates a DynamicConfiguration instance."""
    static_file = tmp_path / "config.yaml"
    static_file.write_text(yaml.dump({}))
    dynamic_file = str(tmp_path / "dynamic.json")

    linked = LinkedConfiguration(
        static_file=str(static_file),
        dynamic_file=dynamic_file,
    )

    assert isinstance(linked.dynamic, DynamicConfiguration)
    assert linked.dynamic.data["report_interval"] == DEFAULT_REPORT_INTERVAL


def test_dynamic_config_replaces_invalid_values_with_defaults(tmp_path):
    """Non-numeric values saved by older versions don't stop the service starting."""
    dynamic_file = tmp_path / "dynamic.json"
    dynamic_file.write_text(
        json.dumps(
            {
                "report_interval": "abc",
                "battery_warning_threshold": None,
                "battery_voltage_minimum": True,
                "battery_voltage_maximum": 4.1,
            },
        ),
    )

    config = DynamicConfiguration(dynamic_file=str(dynamic_file))

    assert config.data["report_interval"] == DEFAULT_REPORT_INTERVAL
    assert config.data["battery_warning_threshold"] == DEFAULT_BATTERY_WARNING_THRESHOLD
    assert config.data["battery_voltage_minimum"] == DEFAULT_BATTERY_VOLTAGE_MINIMUM
    assert config.data["battery_voltage_maximum"] == 4.1


def test_dynamic_config_resets_inverted_voltage_range(tmp_path):
    """A saved minimum voltage above the maximum is reset to the defaults."""
    dynamic_file = tmp_path / "dynamic.json"
    dynamic_file.write_text(
        json.dumps({"battery_voltage_minimum": 4.5, "battery_voltage_maximum": 4.2}),
    )

    config = DynamicConfiguration(dynamic_file=str(dynamic_file))

    assert config.data["battery_voltage_minimum"] == DEFAULT_BATTERY_VOLTAGE_MINIMUM
    assert config.data["battery_voltage_maximum"] == DEFAULT_BATTERY_VOLTAGE_MAXIMUM


def test_dynamic_config_write_replaces_file_atomically(tmp_path):
    """write() leaves only the complete file behind, no temporary file."""
    dynamic_file = tmp_path / "dynamic.json"
    config = DynamicConfiguration(dynamic_file=str(dynamic_file))

    config.data["report_interval"] = 60
    config.write()

    assert json.loads(dynamic_file.read_text())["report_interval"] == 60
    assert [path.name for path in tmp_path.iterdir()] == ["dynamic.json"]


def test_linked_config_client_id_defaults_to_hostname(tmp_path):
    """Without a configured client_id, each hostname gets its own MQTT client ID."""
    static_file = tmp_path / "config.yaml"
    static_file.write_text(yaml.dump({"hostname": {"name": "garage-pi"}}))

    config = LinkedConfiguration(str(static_file), str(tmp_path / "dynamic.json"))

    assert config.static["mqtt"]["client_id"] == "redreactor-garage-pi"


def test_linked_config_keeps_configured_client_id(tmp_path):
    """A configured client_id is used as given."""
    static_file = tmp_path / "config.yaml"
    static_file.write_text(yaml.dump({"mqtt": {"client_id": "my-client"}}))

    config = LinkedConfiguration(str(static_file), str(tmp_path / "dynamic.json"))

    assert config.static["mqtt"]["client_id"] == "my-client"


@pytest.mark.parametrize("contents", ["not json {", "[1, 2]", '"text"'])
def test_dynamic_config_unreadable_file_uses_defaults(tmp_path, contents):
    """A corrupt or non-object dynamic file falls back to the defaults."""
    dynamic_file = tmp_path / "dynamic.json"
    dynamic_file.write_text(contents)

    config = DynamicConfiguration(dynamic_file=str(dynamic_file))

    assert config.data["report_interval"] == DEFAULT_REPORT_INTERVAL


@pytest.mark.parametrize("interval", [0, -5])
def test_dynamic_config_rejects_non_positive_report_interval(tmp_path, interval):
    """A report interval of 0 or less would spin the report timer."""
    dynamic_file = tmp_path / "dynamic.json"
    dynamic_file.write_text(json.dumps({"report_interval": interval}))

    config = DynamicConfiguration(dynamic_file=str(dynamic_file))

    assert config.data["report_interval"] == DEFAULT_REPORT_INTERVAL


def test_linked_config_empty_static_file_uses_defaults(tmp_path):
    """An empty static file loads as None, which is treated as no overrides."""
    static_file = tmp_path / "config.yaml"
    static_file.write_text("")

    config = LinkedConfiguration(str(static_file), str(tmp_path / "dynamic.json"))

    assert config.static["mqtt"]["port"] == 1883


def test_linked_config_accepts_example_config(tmp_path):
    """The example configuration shipped in extras/ passes validation."""
    example = Path(__file__).parent.parent / "extras" / "config.yaml"

    LinkedConfiguration(str(example), str(tmp_path / "dynamic.json"))


@pytest.mark.parametrize(
    ("override", "path"),
    [
        ("- just\n- a list\n", "mapping of options"),
        ("mqtt:\n", "`mqtt` must be a mapping"),
        ("mqtt: {topic: state}\n", "`mqtt.topic` must be a mapping"),
        ("mqtt: {port: 'abc'}\n", "`mqtt.port`"),
        ("mqtt: {port: 70000}\n", "`mqtt.port`"),
        ("mqtt: {port: true}\n", "`mqtt.port`"),
        ("mqtt: {version: 4}\n", "`mqtt.version`"),
        ("mqtt: {timeout: -1}\n", "`mqtt.timeout`"),
        ("mqtt: {exit_on_fail: 'no thanks'}\n", "`mqtt.exit_on_fail`"),
        ("mqtt: {base_topic: 'red/#'}\n", "`mqtt.base_topic`"),
        ("mqtt: {topic: {set: 'a/b'}}\n", "`mqtt.topic.set`"),
        ("homeassistant: {discovery: 'yes'}\n", "`homeassistant.discovery`"),
        (
            "homeassistant: {discovery_interval: 0}\n",
            "`homeassistant.discovery_interval`",
        ),
        ("homeassistant: {expire_after: -1}\n", "`homeassistant.expire_after`"),
        ("hostname: {name: 'my pi/2'}\n", "`hostname.name`"),
        ("hostname: {name: ''}\n", "`hostname.name`"),
        ("ina: {address: 0x80}\n", "`ina.address`"),
        ("ina: {address: '0x40'}\n", "`ina.address`"),
        ("ina: {monitor_interval: 0}\n", "`ina.monitor_interval`"),
        ("ina: {shunt_ohms: .nan}\n", "`ina.shunt_ohms`"),
        ("system: {shutdown: ''}\n", "`system.shutdown`"),
    ],
)
def test_linked_config_rejects_invalid_values(tmp_path, override, path):
    """Invalid static values stop start-up with a message naming the option."""
    static_file = tmp_path / "config.yaml"
    static_file.write_text(override)

    with pytest.raises(ConfigurationError, match=path):
        LinkedConfiguration(str(static_file), str(tmp_path / "dynamic.json"))


def test_linked_config_lists_every_invalid_value(tmp_path):
    """All problems are reported at once, not one per restart."""
    static_file = tmp_path / "config.yaml"
    static_file.write_text("mqtt: {port: 0, version: 4}\n")

    with pytest.raises(ConfigurationError) as error:
        LinkedConfiguration(str(static_file), str(tmp_path / "dynamic.json"))

    assert "`mqtt.port`" in str(error.value)
    assert "`mqtt.version`" in str(error.value)


def test_linked_config_converts_quoted_values(tmp_path):
    """Quoted numbers and booleans that earlier versions accepted still work."""
    static_file = tmp_path / "config.yaml"
    static_file.write_text(
        "mqtt: {port: '1884', exit_on_fail: 'False'}\n"
        "ina: {shunt_ohms: '0.1'}\n",
    )

    config = LinkedConfiguration(str(static_file), str(tmp_path / "dynamic.json"))

    assert config.static["mqtt"]["port"] == 1884
    assert config.static["mqtt"]["exit_on_fail"] is False
    assert config.static["ina"]["shunt_ohms"] == 0.1


def test_dynamic_config_defaults_battery_runtime_limit_to_off(tmp_path):
    """Older dynamic files without the runtime limit get it switched off."""
    dynamic_file = tmp_path / "dynamic.json"
    dynamic_file.write_text(json.dumps({"report_interval": 60}))

    config = DynamicConfiguration(dynamic_file=str(dynamic_file))

    assert config.data["battery_runtime_limit"] == 0
    assert config.data["battery_capacity"] == 0
    assert config.data["report_interval"] == 60


def test_linked_config_new_defaults(tmp_path):
    """New options have defaults, so existing config files keep working."""
    static_file = tmp_path / "config.yaml"
    static_file.write_text(yaml.dump({"hostname": {"name": "garage-pi"}}))

    config = LinkedConfiguration(str(static_file), str(tmp_path / "dynamic.json"))

    assert config.static["ina"]["bus"] == 1
    assert config.static["mqtt"]["tls"]["enabled"] is False
    assert config.static["fields"]["power"]["unit"] == "W"
    assert config.static["fields"]["charging"]["type"] == "binary_sensor"
    assert config.static["fields"]["battery_runtime_limit"]["type"] == "number"
    assert config.static["fields"]["battery_capacity"]["unit"] == "mAh"
    assert config.static["fields"]["battery_time_remaining"]["type"] == "sensor"
    assert config.static["fields"]["cpu_stat_raw"]["state_class"] is None
    assert (
        config.static["fields"]["battery_warning_threshold"]["pretty"]
        == "Battery shutdown level"
    )


def test_linked_config_overrides_new_options(tmp_path):
    """The I2C bus and TLS can be set from the config file."""
    static_file = tmp_path / "config.yaml"
    static_file.write_text(
        yaml.dump(
            {
                "ina": {"bus": 0},
                "mqtt": {"tls": {"enabled": True, "ca_certs": "/etc/ca.crt"}},
            },
        ),
    )

    config = LinkedConfiguration(str(static_file), str(tmp_path / "dynamic.json"))

    assert config.static["ina"]["bus"] == 0
    assert config.static["ina"]["address"] == 0x40
    assert config.static["mqtt"]["tls"]["enabled"] is True
    assert config.static["mqtt"]["tls"]["ca_certs"] == "/etc/ca.crt"
    assert config.static["mqtt"]["tls"]["insecure"] is False


def test_linked_config_converts_quoted_new_options(tmp_path):
    """Quoted I2C bus and TLS flags are converted like the other options."""
    static_file = tmp_path / "config.yaml"
    static_file.write_text(
        "ina: {bus: '2'}\nmqtt: {tls: {enabled: 'true', insecure: 'False'}}\n",
    )

    config = LinkedConfiguration(str(static_file), str(tmp_path / "dynamic.json"))

    assert config.static["ina"]["bus"] == 2
    assert config.static["mqtt"]["tls"]["enabled"] is True
    assert config.static["mqtt"]["tls"]["insecure"] is False


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("ina: {bus: -1}", "`ina.bus`"),
        ("ina: {bus: 1.5}", "`ina.bus`"),
        ("ina: {bus: true}", "`ina.bus`"),
        ("mqtt: {tls: yes}", "`mqtt.tls` must be a mapping"),
        ("mqtt: {tls: {enabled: 'maybe'}}", "`mqtt.tls.enabled`"),
        ("mqtt: {tls: {insecure: 1}}", "`mqtt.tls.insecure`"),
        ("mqtt: {tls: {ca_certs: 5}}", "`mqtt.tls.ca_certs`"),
        ("battery: {curve: [[3.0, 0]]}", "`battery.curve`"),
        ("battery: {curve: [[3.6, 0], [3.0, 100]]}", "`battery.curve`"),
        ("battery: {curve: [[3.0, 50], [3.6, 10]]}", "`battery.curve`"),
        ("battery: {curve: [[3.0, 0], [3.6, 101]]}", "`battery.curve`"),
        ("battery: {curve: [[3.0, 0], ['3.6', 100]]}", "`battery.curve`"),
        ("battery: {curve: 3.0}", "`battery.curve`"),
        ("battery: {internal_resistance: -1}", "`battery.internal_resistance`"),
        ("battery: {average_readings: 0}", "`battery.average_readings`"),
        ("battery: {average_readings: 101}", "`battery.average_readings`"),
        ("battery: {average_readings: 2.5}", "`battery.average_readings`"),
        ("battery: {internal_resistance: abc}", "`battery.internal_resistance`"),
    ],
)
def test_linked_config_rejects_invalid_new_options(tmp_path, contents, message):
    """Invalid I2C bus or TLS settings fail at start with a clear message."""
    static_file = tmp_path / "config.yaml"
    static_file.write_text(contents)

    with pytest.raises(ConfigurationError, match=message.replace(".", r"\.")):
        LinkedConfiguration(str(static_file), str(tmp_path / "dynamic.json"))


def test_dynamic_config_resets_negative_runtime_limit(tmp_path):
    """A negative runtime limit in the dynamic file falls back to off."""
    dynamic_file = tmp_path / "dynamic.json"
    dynamic_file.write_text(json.dumps({"battery_runtime_limit": -5}))

    config = DynamicConfiguration(dynamic_file=str(dynamic_file))

    assert config.data["battery_runtime_limit"] == 0


def test_dynamic_config_resets_negative_battery_capacity(tmp_path):
    """A negative battery capacity in the dynamic file falls back to not set."""
    dynamic_file = tmp_path / "dynamic.json"
    dynamic_file.write_text(json.dumps({"battery_capacity": -3000}))

    config = DynamicConfiguration(dynamic_file=str(dynamic_file))

    assert config.data["battery_capacity"] == 0


def test_linked_config_accepts_battery_curve(tmp_path):
    """A rising voltage curve is accepted, and none is the default."""
    static_file = tmp_path / "config.yaml"
    static_file.write_text("battery: {curve: [[3.0, 0], [3.6, 50], [4.1, 100]]}")

    config = LinkedConfiguration(str(static_file), str(tmp_path / "dynamic.json"))

    assert config.static["battery"]["curve"][1] == [3.6, 50]
    assert config.static["battery"]["internal_resistance"] == 0
    assert config.static["battery"]["average_readings"] == 6


def test_linked_config_converts_quoted_internal_resistance(tmp_path):
    """A quoted internal resistance is read as a number."""
    static_file = tmp_path / "config.yaml"
    static_file.write_text("battery: {internal_resistance: '85'}")

    config = LinkedConfiguration(str(static_file), str(tmp_path / "dynamic.json"))

    assert config.static["battery"]["internal_resistance"] == 85
