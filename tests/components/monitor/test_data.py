"""Tests for MonitorData."""

from __future__ import annotations

from redreactor.components.monitor.data import MonitorData
from redreactor.const import (
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
    DEFAULT_BATTERY_VOLTAGE_MINIMUM,
    DEFAULT_BATTERY_WARNING_THRESHOLD,
    DEFAULT_REPORT_INTERVAL,
)


def test_monitor_data_defaults():
    """MonitorData instantiates with expected defaults."""
    data = MonitorData()
    assert data.voltage == 0.0
    assert data.current == 0.0
    assert data.battery_level == 0.0
    assert data.external_power is True
    assert data.cpu_temperature == 0.0
    assert data.cpu_stat_raw == 0
    assert data.cpu_stat_text == "OK"
    assert data.battery_warning_threshold == DEFAULT_BATTERY_WARNING_THRESHOLD
    assert data.battery_voltage_minimum == DEFAULT_BATTERY_VOLTAGE_MINIMUM
    assert data.battery_voltage_maximum == DEFAULT_BATTERY_VOLTAGE_MAXIMUM
    assert data.report_interval == DEFAULT_REPORT_INTERVAL


def test_monitor_data_custom_values():
    """MonitorData instantiates with custom values."""
    data = MonitorData(
        voltage=3.8,
        current=150.0,
        battery_level=75,
        external_power=False,
        cpu_temperature=55.0,
        cpu_stat_raw=1,
        cpu_stat_text="Under-voltage NOW",
        battery_warning_threshold=20,
        battery_voltage_minimum=3.0,
        battery_voltage_maximum=4.1,
        report_interval=60,
    )
    assert data.voltage == 3.8
    assert data.current == 150.0
    assert data.battery_level == 75
    assert data.external_power is False
    assert data.cpu_temperature == 55.0
    assert data.cpu_stat_raw == 1
    assert data.cpu_stat_text == "Under-voltage NOW"
    assert data.battery_warning_threshold == 20
    assert data.battery_voltage_minimum == 3.0
    assert data.battery_voltage_maximum == 4.1
    assert data.report_interval == 60


def test_monitor_data_attributes_readable_and_writable():
    """MonitorData attributes can be read and overwritten."""
    data = MonitorData()
    data.voltage = 4.0
    data.current = -100.0
    data.battery_level = 50
    data.external_power = False
    assert data.voltage == 4.0
    assert data.current == -100.0
    assert data.battery_level == 50
    assert data.external_power is False
