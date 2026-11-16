"""Tests for the Monitor's settable readings, sensor problem and reports."""

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
# Settings changed from Home Assistant
# ---------------------------------------------------------------------------


def test_monitor_interval_comes_from_the_static_configuration(monitor):
    """Until it is changed from Home Assistant, the static value is used."""
    assert monitor.data.monitor_interval == 5
    assert monitor.monitor_timer.interval == 5


def test_monitor_interval_change_is_applied(monitor, dynamic_config, published):
    """A new monitor interval changes the timer straight away and is reported."""
    dynamic_config.data["monitor_interval"] = 2.5
    dynamic_config.event.emit("write")

    assert monitor.monitor_timer.interval == 2.5
    assert published[-1]["monitor_interval"] == 2.5


def test_average_readings_change_keeps_the_recent_readings(
    monitor,
    dynamic_config,
    mock_ina,
):
    """Fewer readings averaged keeps the most recent ones."""
    dynamic_config.data["average_readings"] = 3
    monitor._update_dynamic_configuration()
    with patch.object(monitor, "_update"):
        for voltage in (3.3, 3.5, 3.7):
            _run_monitor_with_ina(monitor, mock_ina, voltage, 500.0)

    dynamic_config.data["average_readings"] = 2
    monitor._update_dynamic_configuration()

    assert monitor._battery_readings.maxlen == 2
    assert [voltage for voltage, _ in monitor._battery_readings] == [3.5, 3.7]


def test_shutdown_readings_setting_is_used(monitor, dynamic_config, mock_ina):
    """The shutdown waits for the set number of low readings."""
    dynamic_config.data["shutdown_readings"] = 5
    monitor._update_dynamic_configuration()
    shutdowns: list[bool] = []
    monitor.event.on("shutdown", lambda: shutdowns.append(True))

    with patch.object(monitor, "_update"):
        for _ in range(4):
            _run_monitor_with_ina(monitor, mock_ina, 2.9, 500.0)
        assert not shutdowns
        _run_monitor_with_ina(monitor, mock_ina, 2.9, 500.0)

    assert shutdowns == [True]


def test_settings_are_in_the_state(monitor, published):
    """The settable readings values are reported for Home Assistant."""
    monitor._update()

    assert published[-1]["monitor_interval"] == 5
    assert published[-1]["average_readings"] == 1
    assert published[-1]["shutdown_readings"] == 3


# ---------------------------------------------------------------------------
# Sensor problem
# ---------------------------------------------------------------------------


def test_sensor_problem_after_failed_readings(monitor, mock_ina, published):
    """Readings that keep failing are reported as unknown, with the problem."""
    _run_monitor_with_ina(monitor, mock_ina, 3.7, 50.0)
    monitor._update()
    assert published[-1]["sensor_problem"] == "OFF"
    assert published[-1]["voltage"] == 3.7

    for _ in range(SENSOR_PROBLEM_READINGS - 1):
        _fail_reading(monitor, mock_ina)
    assert not monitor.data.sensor_problem

    reports = len(published)
    _fail_reading(monitor, mock_ina)

    assert monitor.data.sensor_problem
    assert len(published) == reports + 1
    state = published[-1]
    assert state["sensor_problem"] == "ON"
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


def test_sensor_problem_clears_when_reading_works(monitor, mock_ina, published):
    """A good reading clears the problem and is reported straight away."""
    for _ in range(SENSOR_PROBLEM_READINGS):
        _fail_reading(monitor, mock_ina)
    mock_ina.voltage.side_effect = None

    _run_monitor_with_ina(monitor, mock_ina, 3.7, 50.0)

    assert not monitor.data.sensor_problem
    assert published[-1]["sensor_problem"] == "OFF"
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
# Last shutdown, refresh and the watchdog health check
# ---------------------------------------------------------------------------


def test_last_shutdown_is_reported(static_config, dynamic_config, mock_ina):
    """The shutdown saved before this start is reported."""
    from redreactor.components.mqtt import MQTT

    dynamic_config.data["last_shutdown"] = {
        "reason": "Low battery",
        "action": "shutdown",
        "voltage": 3.21,
        "battery_level": 2,
        "time": "2026-11-10T20:36:00+00:00",
    }
    monitor = _make_monitor(static_config, dynamic_config, mock_ina)
    published: dict[str, str] = {}
    MQTT.event.on(
        "publish",
        lambda topic, payload, **_: published.__setitem__(topic, payload),
    )

    monitor._update()

    state = json.loads(published[STATE_TOPIC])
    assert state["last_shutdown"] == "Low battery"
    assert state["last_shutdown_time"] == "2026-11-10T20:36:00+00:00"
    assert state["last_shutdown_voltage"] == 3.21


@pytest.mark.parametrize("saved", [None, "Low battery", ["Low battery"]])
def test_no_or_invalid_last_shutdown_is_unknown(
    static_config,
    dynamic_config,
    mock_ina,
    saved,
):
    """Without a saved shutdown, or with one that isn't valid, it is unknown."""
    if saved is not None:
        dynamic_config.data["last_shutdown"] = saved
    monitor = _make_monitor(static_config, dynamic_config, mock_ina)

    state = monitor._state_payload()

    assert state["last_shutdown"] is None
    assert state["last_shutdown_time"] is None
    assert state["last_shutdown_voltage"] is None


def test_refresh_reads_and_reports(monitor, mock_ina, published):
    """The refresh button takes a reading and reports it."""
    mock_ina.voltage.return_value = 3.8
    mock_ina.current.return_value = 50.0

    monitor.refresh()

    assert published[-1]["voltage"] == 3.8


def test_refresh_starts_the_shutdown_once(monitor, mock_ina):
    """A refresh at the last low reading starts the shutdown, only once."""
    shutdowns: list[bool] = []
    monitor.event.on("shutdown", lambda: shutdowns.append(True))
    mock_ina.voltage.return_value = 2.9
    mock_ina.current.return_value = 500.0

    with patch.object(monitor, "_update"):
        for _ in range(5):
            monitor.refresh()

    assert shutdowns == [True]


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
