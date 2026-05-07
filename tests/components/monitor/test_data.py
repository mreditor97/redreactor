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
    """MonitorData initialises with expected default values."""
    data = MonitorData()
    assert data.voltage == 0.0
    assert data.current == 0.0
    assert data.external_power is True
    assert data.battery_warning_threshold == DEFAULT_BATTERY_WARNING_THRESHOLD
    assert data.battery_voltage_minimum == DEFAULT_BATTERY_VOLTAGE_MINIMUM
    assert data.battery_voltage_maximum == DEFAULT_BATTERY_VOLTAGE_MAXIMUM
    assert data.report_interval == DEFAULT_REPORT_INTERVAL


def test_monitor_data_custom_values():
    """MonitorData stores custom values passed at construction."""
    data = MonitorData(
        voltage=3.7,
        current=-100.0,
        battery_level=75,
        external_power=False,
        cpu_temperature=55.0,
        cpu_stat_raw=4,
        cpu_stat_text="Throttled NOW",
        battery_warning_threshold=15,
        battery_voltage_minimum=3.0,
        battery_voltage_maximum=4.1,
        report_interval=60,
    )
    assert data.voltage == 3.7
    assert data.current == -100.0
    assert data.battery_level == 75
    assert data.external_power is False
    assert data.cpu_temperature == 55.0
    assert data.cpu_stat_raw == 4
    assert data.cpu_stat_text == "Throttled NOW"
    assert data.battery_warning_threshold == 15
    assert data.battery_voltage_minimum == 3.0
    assert data.battery_voltage_maximum == 4.1
    assert data.report_interval == 60


def test_monitor_data_attributes_are_mutable():
    """MonitorData attributes can be updated after construction."""
    data = MonitorData()
    data.voltage = 4.0
    data.external_power = False
    assert data.voltage == 4.0
    assert data.external_power is False
