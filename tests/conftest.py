"""Shared fixtures for redreactor test suite."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from redreactor.configuration import DynamicConfiguration


@pytest.fixture
def static_config():
    """Return the default static config dict."""
    return {
        "mqtt": {
            "broker": "127.0.0.1",
            "port": 1883,
            "user": "test",
            "password": "test",
            "client_id": "Red Reactor",
            "base_topic": "redreactor",
            "version": 3,
            "transport": "tcp",
            "timeout": 120,
            "topic": {
                "state": "state",
                "status": "status",
                "set": "set",
            },
            "exit_on_fail": True,
        },
        "hostname": {"name": "redreactor", "pretty": "Red Reactor"},
        "homeassistant": {
            "discovery": True,
            "topic": "homeassistant",
            "discovery_interval": 120,
            "expire_after": 120,
        },
        "status": {
            "online": "online",
            "offline": "offline",
        },
        "fields": {
            "voltage": {
                "name": "voltage",
                "pretty": "Voltage",
                "type": "sensor",
                "unit": "V",
                "device_class": "voltage",
                "suggested_display_precision": 2,
            },
            "current": {
                "name": "current",
                "pretty": "Current",
                "type": "sensor",
                "unit": "mA",
                "device_class": "current",
                "suggested_display_precision": 2,
            },
            "power": {
                "name": "power",
                "pretty": "Power",
                "type": "sensor",
                "unit": "W",
                "device_class": "power",
                "suggested_display_precision": 2,
            },
            "battery_level": {
                "name": "battery_level",
                "pretty": "Battery level",
                "type": "sensor",
                "unit": "%",
                "device_class": "battery",
            },
            "external_power": {
                "name": "external_power",
                "pretty": "External power",
                "type": "binary_sensor",
                "device_class": "plug",
                "entity_category": "diagnostic",
            },
            "charging": {
                "name": "charging",
                "pretty": "Charging",
                "type": "binary_sensor",
                "device_class": "battery_charging",
            },
            "cpu_temperature": {
                "name": "cpu_temperature",
                "pretty": "CPU temperature",
                "type": "sensor",
                "unit": "°C",
                "device_class": "temperature",
                "entity_category": "diagnostic",
                "suggested_display_precision": 2,
            },
            "cpu_stat_raw": {
                "name": "cpu_stat_raw",
                "pretty": "CPU stat raw",
                "type": "sensor",
                "entity_category": "diagnostic",
                "enabled_by_default": False,
                "state_class": None,
            },
            "cpu_stat_text": {
                "name": "cpu_stat",
                "pretty": "CPU stat",
                "type": "sensor",
                "entity_category": "diagnostic",
                "state_class": None,
            },
            "battery_warning_threshold": {
                "name": "battery_warning_threshold",
                "pretty": "Battery shutdown level",
                "type": "number",
                "unit": "%",
                "device_class": "battery",
                "entity_category": "diagnostic",
                "min": 0,
                "max": 100,
                "mode": "box",
                "step": 1,
            },
            "battery_voltage_minimum": {
                "name": "battery_voltage_minimum",
                "pretty": "Battery voltage minimum",
                "type": "number",
                "unit": "V",
                "device_class": "voltage",
                "entity_category": "diagnostic",
                "min": 2.5,
                "max": 4.5,
                "mode": "box",
                "step": 0.1,
            },
            "battery_voltage_maximum": {
                "name": "battery_voltage_maximum",
                "pretty": "Battery voltage maximum",
                "type": "number",
                "unit": "V",
                "device_class": "voltage",
                "entity_category": "diagnostic",
                "min": 2.5,
                "max": 4.5,
                "mode": "box",
                "step": 0.1,
            },
            "report_interval": {
                "name": "report_interval",
                "pretty": "Report interval",
                "type": "number",
                "unit": "s",
                "entity_category": "diagnostic",
                "min": 5,
                "max": 300,
                "mode": "box",
                "step": 5,
            },
            "battery_runtime_limit": {
                "name": "battery_runtime_limit",
                "pretty": "Battery runtime limit",
                "type": "number",
                "unit": "min",
                "device_class": "duration",
                "entity_category": "diagnostic",
                "min": 0,
                "max": 1440,
                "mode": "box",
                "step": 1,
            },
            "battery_capacity": {
                "name": "battery_capacity",
                "pretty": "Battery capacity",
                "type": "number",
                "unit": "mAh",
                "entity_category": "diagnostic",
                "min": 0,
                "max": 20000,
                "mode": "box",
                "step": 1,
            },
            "battery_time_remaining": {
                "name": "battery_time_remaining",
                "pretty": "Battery time remaining",
                "type": "sensor",
                "unit": "min",
                "device_class": "duration",
                "suggested_display_precision": 0,
            },
            "restart": {
                "name": "restart",
                "pretty": "Restart",
                "type": "button",
                "entity_category": "diagnostic",
            },
            "shutdown": {
                "name": "shutdown",
                "pretty": "Shutdown",
                "type": "button",
                "entity_category": "diagnostic",
            },
        },
        "ina": {
            "address": 0x40,
            "shunt_ohms": 0.05,
            "max_expected_amps": 5.5,
            "monitor_interval": 5,
            "bus": 1,
        },
        "battery": {
            "internal_resistance": 0,
            "average_readings": 1,
            "curve": None,
        },
        "system": {
            "shutdown": "sudo shutdown 0 -h",
            "restart": "sudo shutdown 0 -r",
        },
        "logging": {
            "console": "INFO",
            "file": "WARNING",
        },
    }


@pytest.fixture
def dynamic_config(tmp_path):
    """Create a real DynamicConfiguration using a tmp_path JSON file."""
    dynamic_file = str(tmp_path / "dynamic.json")
    return DynamicConfiguration(dynamic_file=dynamic_file)


@pytest.fixture
def mock_ina():
    """Return a MagicMock patching ina219.INA219."""
    mock = MagicMock()
    mock.voltage.return_value = 3.7
    mock.current.return_value = -50.0
    mock.power.return_value = 185.0
    mock.configure.return_value = None
    mock.RANGE_16V = 0
    return mock
