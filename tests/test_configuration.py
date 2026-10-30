"""Tests for configuration module."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from redreactor.configuration import DynamicConfiguration, LinkedConfiguration
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
