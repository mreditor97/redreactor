"""Tests for configuration module."""

from __future__ import annotations

import json

import pytest
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

    with open(dynamic_file) as f:
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
