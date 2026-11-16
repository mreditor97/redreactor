"""Tests for the Monitor's shutdown readings, failed readings and reports."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from redreactor.const import (
    REPORT_ON_CHANGE_MINIMUM_INTERVAL,
    SENSOR_PROBLEM_READINGS,
)

from .test_monitor import VOLTAGE_49_PERCENT, _make_monitor, _run_monitor_with_ina

STATE_TOPIC = "redreactor/redreactor/state"


@pytest.fixture
def monitor(static_config, dynamic_config, mock_ina):
    """Return a Monitor instance with all hardware mocked."""
    return _make_monitor(static_config, dynamic_config, mock_ina)


@pytest.fixture
def published(monitor):  # noqa: ARG001 Built first, as it resets MQTT.event
    """Collect the state reports the monitor publishes."""
    from redreactor.components.mqtt import MQTT

    states: list[dict] = []

    def record(topic: str, payload: str, **_: object) -> None:
        if topic == STATE_TOPIC:
            states.append(json.loads(payload))

    MQTT.event.on("publish", record)
    return states


def _fail_reading(monitor, mock_ina):
    mock_ina.voltage.side_effect = OSError(121, "Remote I/O error")
    monitor._monitor(ina=mock_ina)


# ---------------------------------------------------------------------------
# Shutdown readings
# ---------------------------------------------------------------------------


def test_shutdown_readings_setting_is_used(static_config, dynamic_config, mock_ina):
    """The shutdown waits for battery.shutdown_readings low readings."""
    static_config["battery"]["shutdown_readings"] = 5
    monitor = _make_monitor(static_config, dynamic_config, mock_ina)
    shutdowns: list[bool] = []
    monitor.event.on("shutdown", lambda: shutdowns.append(True))

    with patch.object(monitor, "_update"):
        for _ in range(4):
            _run_monitor_with_ina(monitor, mock_ina, 2.9, 500.0)
        assert not shutdowns
        _run_monitor_with_ina(monitor, mock_ina, 2.9, 500.0)

    assert shutdowns == [True]


# ---------------------------------------------------------------------------
# Failed readings
# ---------------------------------------------------------------------------


def test_failed_readings_are_reported_as_unknown(monitor, mock_ina, published):
    """Readings that keep failing are reported as unknown."""
    _run_monitor_with_ina(monitor, mock_ina, 3.7, 50.0)
    monitor._update()
    assert published[-1]["voltage"] == 3.7

    for _ in range(SENSOR_PROBLEM_READINGS - 1):
        _fail_reading(monitor, mock_ina)
    assert not monitor._sensor_problem

    reports = len(published)
    _fail_reading(monitor, mock_ina)

    assert monitor._sensor_problem
    assert len(published) == reports + 1
    state = published[-1]
    for name in (
        "voltage",
        "current",
        "power",
        "battery_level",
        "external_power",
        "charging",
        "battery_time_remaining",
    ):
        assert state[name] is None, name

    # Reported once, not on every failed reading after that
    _fail_reading(monitor, mock_ina)
    assert len(published) == reports + 1


def test_readings_are_reported_again_when_reading_works(monitor, mock_ina, published):
    """A good reading after the failures is reported straight away."""
    for _ in range(SENSOR_PROBLEM_READINGS):
        _fail_reading(monitor, mock_ina)
    mock_ina.voltage.side_effect = None

    _run_monitor_with_ina(monitor, mock_ina, 3.7, 50.0)

    assert not monitor._sensor_problem
    assert published[-1]["voltage"] == 3.7


# ---------------------------------------------------------------------------
# Report on change
# ---------------------------------------------------------------------------


def _report_then_wait(monitor):
    """Send a report, then make it old enough for a change to be reported."""
    monitor._update()
    monitor._reported_at -= REPORT_ON_CHANGE_MINIMUM_INTERVAL


def test_level_change_is_reported(monitor, mock_ina, published):
    """A level change of report_level_change points is reported straight away."""
    _run_monitor_with_ina(monitor, mock_ina, 4.0, 50.0)
    _report_then_wait(monitor)
    reports = len(published)

    # A small change waits for the report interval
    _run_monitor_with_ina(monitor, mock_ina, 3.99, 50.0)
    assert len(published) == reports

    _run_monitor_with_ina(monitor, mock_ina, VOLTAGE_49_PERCENT, 50.0)
    assert len(published) == reports + 1
    assert published[-1]["battery_level"] == monitor.data.battery_level


def test_charging_change_is_reported(monitor, mock_ina, published):
    """Starting to charge is reported straight away."""
    _run_monitor_with_ina(monitor, mock_ina, 3.7, 5.0)
    _report_then_wait(monitor)
    reports = len(published)

    _run_monitor_with_ina(monitor, mock_ina, 3.7, -200.0)

    assert len(published) == reports + 1
    assert published[-1]["charging"] == "ON"


def test_changes_are_not_reported_too_often(monitor, mock_ina, published):
    """A change right after a report waits."""
    _run_monitor_with_ina(monitor, mock_ina, 3.7, 5.0)
    monitor._update()
    reports = len(published)

    _run_monitor_with_ina(monitor, mock_ina, 3.7, -200.0)

    assert len(published) == reports


def test_nothing_is_reported_before_the_first_report(monitor, mock_ina, published):
    """A change before anything is reported doesn't report."""
    _run_monitor_with_ina(monitor, mock_ina, 4.0, 5.0)
    _run_monitor_with_ina(monitor, mock_ina, 3.3, -200.0)

    assert published == []


def test_level_change_can_be_turned_off(static_config, dynamic_config, mock_ina):
    """A report_level_change of 0 only reports charging changes."""
    from redreactor.components.mqtt import MQTT

    static_config["battery"]["report_level_change"] = 0
    monitor = _make_monitor(static_config, dynamic_config, mock_ina)
    published: list[str] = []
    MQTT.event.on("publish", lambda topic, **_: published.append(topic))

    _run_monitor_with_ina(monitor, mock_ina, 4.0, 50.0)
    _report_then_wait(monitor)
    reports = len(published)
    _run_monitor_with_ina(monitor, mock_ina, VOLTAGE_49_PERCENT, 50.0)

    assert len(published) == reports


# ---------------------------------------------------------------------------
# The watchdog health check
# ---------------------------------------------------------------------------


def test_is_healthy_while_readings_are_taken(monitor, mock_ina):
    """The watchdog check fails once the readings have stopped."""
    with patch.object(monitor, "_update"):
        _run_monitor_with_ina(monitor, mock_ina)
    assert monitor.is_healthy()

    monitor._last_tick -= 3600
    assert not monitor.is_healthy()

    # Stopping for a shutdown or restart is expected
    monitor.stop()
    assert monitor.is_healthy()
