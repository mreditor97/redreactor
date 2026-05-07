"""Tests for the Monitor component."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from redreactor.components.monitor.data import MonitorData
from redreactor.const import (
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
    DEFAULT_BATTERY_VOLTAGE_MINIMUM,
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP,
)
from redreactor.helpers.emitter import EventEmitter


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_monitor(static_config, dynamic_config, mock_ina_instance):
    """Construct a Monitor with mocked INA219 and MQTT event."""
    from redreactor.components.monitor.monitor import Monitor
    from redreactor.components.mqtt import MQTT

    # Reset class-level state before each monitor construction
    Monitor.event = EventEmitter()
    Monitor.data = MonitorData(
        voltage=0.0,
        current=0.0,
        battery_level=100,
        external_power=True,
    )

    # Patch MQTT.event so no real MQTT calls happen
    MQTT.event = EventEmitter()

    # Patch at the module where INA219 is imported (the monitor module)
    with patch("redreactor.components.monitor.monitor.INA219", return_value=mock_ina_instance):
        monitor = Monitor(
            static_configuration=static_config,
            dynamic_configuration=dynamic_config,
        )

    # Stop the running timers so tests don't have side-effects
    monitor.monitor_timer.stop()
    if monitor.report_timer.is_running:
        monitor.report_timer.stop()

    return monitor


@pytest.fixture
def monitor(static_config, dynamic_config, mock_ina):
    """Return a Monitor instance with all hardware mocked."""
    return _make_monitor(static_config, dynamic_config, mock_ina)


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


def test_monitor_init_succeeds(static_config, dynamic_config, mock_ina):
    """Monitor.__init__ succeeds when INA219 is mocked."""
    from redreactor.components.monitor.monitor import Monitor
    from redreactor.components.mqtt import MQTT

    Monitor.event = EventEmitter()
    Monitor.data = MonitorData()
    MQTT.event = EventEmitter()

    with patch("redreactor.components.monitor.monitor.INA219", return_value=mock_ina):
        m = Monitor(
            static_configuration=static_config,
            dynamic_configuration=dynamic_config,
        )

    m.monitor_timer.stop()
    assert m is not None


# ---------------------------------------------------------------------------
# _calculate_battery_level
# ---------------------------------------------------------------------------


def test_calculate_battery_level_at_minimum(monitor):
    """Voltage at battery_voltage_minimum should give 0%."""
    monitor.data.battery_voltage_minimum = DEFAULT_BATTERY_VOLTAGE_MINIMUM
    monitor.data.battery_voltage_maximum = DEFAULT_BATTERY_VOLTAGE_MAXIMUM
    result = monitor._calculate_battery_level(DEFAULT_BATTERY_VOLTAGE_MINIMUM)
    assert result == 0


def test_calculate_battery_level_at_maximum(monitor):
    """Voltage at or above effective max should give 100%."""
    monitor.data.battery_voltage_minimum = DEFAULT_BATTERY_VOLTAGE_MINIMUM
    monitor.data.battery_voltage_maximum = DEFAULT_BATTERY_VOLTAGE_MAXIMUM
    effective_max = DEFAULT_BATTERY_VOLTAGE_MAXIMUM - DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP
    result = monitor._calculate_battery_level(effective_max)
    assert result == 100


def test_calculate_battery_level_midpoint(monitor):
    """Voltage at midpoint returns a value between 0 and 100."""
    monitor.data.battery_voltage_minimum = DEFAULT_BATTERY_VOLTAGE_MINIMUM
    monitor.data.battery_voltage_maximum = DEFAULT_BATTERY_VOLTAGE_MAXIMUM
    mid = (DEFAULT_BATTERY_VOLTAGE_MINIMUM + DEFAULT_BATTERY_VOLTAGE_MAXIMUM) / 2
    result = monitor._calculate_battery_level(mid)
    assert 0 < result < 100


def test_calculate_battery_level_above_max_clamped(monitor):
    """Voltage above effective max is clamped to 100."""
    monitor.data.battery_voltage_minimum = DEFAULT_BATTERY_VOLTAGE_MINIMUM
    monitor.data.battery_voltage_maximum = DEFAULT_BATTERY_VOLTAGE_MAXIMUM
    result = monitor._calculate_battery_level(5.0)  # Way above max
    assert result == 100


def test_calculate_battery_level_below_min_clamped(monitor):
    """Voltage below battery_voltage_minimum is clamped to 0."""
    monitor.data.battery_voltage_minimum = DEFAULT_BATTERY_VOLTAGE_MINIMUM
    monitor.data.battery_voltage_maximum = DEFAULT_BATTERY_VOLTAGE_MAXIMUM
    result = monitor._calculate_battery_level(1.0)  # Way below min
    assert result == 0


# ---------------------------------------------------------------------------
# _monitor behaviour
# ---------------------------------------------------------------------------


def _run_monitor_with_ina(monitor, ina_mock, voltage=3.7, current=-50.0):
    """Helper to run _monitor with a configured INA mock."""
    ina_mock.voltage.return_value = voltage
    ina_mock.current.return_value = current
    monitor._monitor(ina=ina_mock)


def test_monitor_high_current_sets_external_power_false(monitor, mock_ina):
    """current > 10 sets external_power=False when it was True."""
    monitor.data.external_power = True
    with patch.object(monitor, "_update"):
        _run_monitor_with_ina(monitor, mock_ina, voltage=3.7, current=50.0)
    assert monitor.data.external_power is False


def test_monitor_zero_to_ten_current_sets_external_power_true(monitor, mock_ina):
    """current in [0, 10] sets external_power=True."""
    monitor.data.external_power = False
    with patch.object(monitor, "_update"):
        _run_monitor_with_ina(monitor, mock_ina, voltage=3.7, current=5.0)
    assert monitor.data.external_power is True


def test_monitor_negative_current_sets_external_power_true(monitor, mock_ina):
    """Negative current (charging) sets external_power=True."""
    monitor.data.external_power = False
    with patch.object(monitor, "_update"):
        _run_monitor_with_ina(monitor, mock_ina, voltage=3.7, current=-50.0)
    assert monitor.data.external_power is True


def test_monitor_device_range_error_sets_external_power_false(
    monitor, mock_ina, static_config
):
    """DeviceRangeError sets external_power=False and current=6000."""
    from ina219 import DeviceRangeError

    monitor.data.external_power = True
    mock_ina.voltage.side_effect = DeviceRangeError(6000)

    from redreactor.components.mqtt import MQTT
    MQTT.event = EventEmitter()

    monitor._monitor(ina=mock_ina)

    assert monitor.data.external_power is False
    assert monitor.data.current == 6000


def test_monitor_battery_zero_no_external_power_emits_shutdown(monitor, mock_ina):
    """battery_level == 0 and not external_power emits 'shutdown' event."""
    mock_ina.voltage.return_value = DEFAULT_BATTERY_VOLTAGE_MINIMUM
    mock_ina.current.return_value = 50.0  # High current → no external power

    monitor.data.battery_voltage_minimum = DEFAULT_BATTERY_VOLTAGE_MINIMUM
    monitor.data.battery_voltage_maximum = DEFAULT_BATTERY_VOLTAGE_MAXIMUM
    monitor.data.external_power = True  # Will be set to False due to high current

    shutdown_called = []
    monitor.event.on("shutdown", lambda: shutdown_called.append(True))

    with patch.object(monitor, "_update"):
        monitor._monitor(ina=mock_ina)

    assert shutdown_called, "shutdown event was not emitted"


def test_monitor_voltage_above_max_forces_external_power(monitor, mock_ina):
    """Voltage above battery_voltage_maximum + 0.05 forces external_power=True."""
    monitor.data.battery_voltage_maximum = DEFAULT_BATTERY_VOLTAGE_MAXIMUM
    monitor.data.external_power = False

    high_voltage = DEFAULT_BATTERY_VOLTAGE_MAXIMUM + 0.10
    mock_ina.voltage.return_value = high_voltage
    mock_ina.current.return_value = -50.0  # negative → power is on

    with patch.object(monitor, "_update"):
        monitor._monitor(ina=mock_ina)

    assert monitor.data.external_power is True
