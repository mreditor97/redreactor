"""Tests for the Monitor component."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from redreactor.components.monitor.data import MonitorData
from redreactor.const import (
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP,
    DEFAULT_BATTERY_VOLTAGE_MINIMUM,
    DEFAULT_SHUTDOWN_CONSECUTIVE_READINGS,
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
    with patch(
        "redreactor.components.monitor.monitor.INA219",
        return_value=mock_ina_instance,
    ):
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
    v_max = DEFAULT_BATTERY_VOLTAGE_MAXIMUM - DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP
    result = monitor._calculate_battery_level(v_max)
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
    """Run _monitor with a configured INA mock."""
    ina_mock.voltage.return_value = voltage
    ina_mock.current.return_value = current
    monitor._monitor(ina=ina_mock)


def test_monitor_high_current_sets_external_power_false(monitor, mock_ina):
    """Current > 10 sets external_power=False when it was True."""
    monitor.data.external_power = True
    with patch.object(monitor, "_update"):
        _run_monitor_with_ina(monitor, mock_ina, voltage=3.7, current=50.0)
    assert monitor.data.external_power is False


def test_monitor_zero_to_ten_current_sets_external_power_true(monitor, mock_ina):
    """Current in [0, 10] sets external_power=True."""
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


def test_monitor_device_range_error_sets_external_power_false(monitor, mock_ina):
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
    mock_ina.current.return_value = 50.0  # High current no external power

    monitor.data.battery_voltage_minimum = DEFAULT_BATTERY_VOLTAGE_MINIMUM
    monitor.data.battery_voltage_maximum = DEFAULT_BATTERY_VOLTAGE_MAXIMUM
    monitor.data.external_power = True  # Will be set to False due to high current

    shutdown_called = []
    monitor.event.on("shutdown", lambda: shutdown_called.append(True))

    with patch.object(monitor, "_update"):
        for _ in range(DEFAULT_SHUTDOWN_CONSECUTIVE_READINGS):
            monitor._monitor(ina=mock_ina)

    assert shutdown_called, "shutdown event was not emitted"


def test_monitor_voltage_above_max_forces_external_power(monitor, mock_ina):
    """Voltage above battery_voltage_maximum + 0.05 forces external_power=True."""
    monitor.data.battery_voltage_maximum = DEFAULT_BATTERY_VOLTAGE_MAXIMUM
    monitor.data.external_power = False

    high_voltage = DEFAULT_BATTERY_VOLTAGE_MAXIMUM + 0.10
    mock_ina.voltage.return_value = high_voltage
    mock_ina.current.return_value = -50.0  # negative power is on

    with patch.object(monitor, "_update"):
        monitor._monitor(ina=mock_ina)

    assert monitor.data.external_power is True


def test_monitor_inverted_voltage_range_still_shuts_down(
    monitor,
    mock_ina,
    dynamic_config,
):
    """A minimum voltage above the maximum must not disable low battery shutdown."""
    dynamic_config.data["battery_voltage_minimum"] = 4.5
    dynamic_config.data["battery_voltage_maximum"] = 4.2
    mock_ina.voltage.return_value = DEFAULT_BATTERY_VOLTAGE_MINIMUM
    mock_ina.current.return_value = 500.0  # Discharging, no external power

    shutdown_called = []
    monitor.event.on("shutdown", lambda: shutdown_called.append(True))

    with patch.object(monitor, "_update"):
        for _ in range(DEFAULT_SHUTDOWN_CONSECUTIVE_READINGS):
            monitor._monitor(ina=mock_ina)

    assert monitor.data.battery_level == 0
    assert shutdown_called, "shutdown event was not emitted"


def test_monitor_single_empty_reading_does_not_shut_down(monitor, mock_ina):
    """One 0% reading (e.g. a voltage sag under load) does not shut down."""
    mock_ina.current.return_value = 500.0
    shutdown_called = []
    monitor.event.on("shutdown", lambda: shutdown_called.append(True))

    with patch.object(monitor, "_update"):
        for _ in range(DEFAULT_SHUTDOWN_CONSECUTIVE_READINGS - 1):
            mock_ina.voltage.return_value = DEFAULT_BATTERY_VOLTAGE_MINIMUM
            monitor._monitor(ina=mock_ina)
        # Recovers above 0%, which resets the count
        mock_ina.voltage.return_value = 3.7
        monitor._monitor(ina=mock_ina)
        mock_ina.voltage.return_value = DEFAULT_BATTERY_VOLTAGE_MINIMUM
        monitor._monitor(ina=mock_ina)

    assert not shutdown_called


def test_monitor_voltage_above_max_publishes_only_on_transition(monitor, mock_ina):
    """High voltage with external power already detected does not republish."""
    monitor.data.external_power = True
    mock_ina.voltage.return_value = DEFAULT_BATTERY_VOLTAGE_MAXIMUM + 0.10
    mock_ina.current.return_value = 5.0  # Float charge, power already present

    with patch.object(monitor, "_update") as update:
        monitor._monitor(ina=mock_ina)
        monitor._monitor(ina=mock_ina)

    update.assert_not_called()
    assert monitor.data.external_power is True


def test_monitor_reads_dynamic_configuration_by_field_key(
    static_config,
    dynamic_config,
    mock_ina,
):
    """Renaming a field's MQTT name doesn't change where its value is stored."""
    static_config["fields"]["report_interval"]["name"] = "interval_seconds"
    dynamic_config.data["report_interval"] = 60

    monitor = _make_monitor(static_config, dynamic_config, mock_ina)

    assert monitor.data.report_interval == 60


# ---------------------------------------------------------------------------
# Power, charging and the shutdown threshold
# ---------------------------------------------------------------------------

# With the default 2.9 V to 4.2 V range these read as 7%, 3% and 49%
VOLTAGE_7_PERCENT = 3.0
VOLTAGE_3_PERCENT = 2.94
VOLTAGE_49_PERCENT = 3.53


def _shutdown_events(monitor):
    calls = []
    monitor.event.on("shutdown", lambda: calls.append(True))
    return calls


def test_monitor_reads_power_in_watts(monitor, mock_ina):
    """pi-ina219 reports milliwatts, published power is in watts."""
    mock_ina.power.return_value = 2500.0
    with patch.object(monitor, "_update"):
        _run_monitor_with_ina(monitor, mock_ina, current=500.0)
    assert monitor.data.power == 2.5


@pytest.mark.parametrize(
    ("current", "charging"),
    [(-50.0, True), (5.0, False), (500.0, False)],
)
def test_monitor_charging_follows_current_sign(monitor, mock_ina, current, charging):
    """Only a negative current means the battery is charging."""
    with patch.object(monitor, "_update"):
        _run_monitor_with_ina(monitor, mock_ina, current=current)
    assert monitor.data.charging is charging


def test_monitor_shuts_down_at_warning_threshold(monitor, mock_ina, dynamic_config):
    """At or below the warning threshold on battery, the device shuts down."""
    dynamic_config.data["battery_warning_threshold"] = 10
    shutdown_called = _shutdown_events(monitor)

    with patch.object(monitor, "_update"):
        for _ in range(DEFAULT_SHUTDOWN_CONSECUTIVE_READINGS):
            _run_monitor_with_ina(monitor, mock_ina, VOLTAGE_7_PERCENT, 500.0)

    assert monitor.data.battery_level == 7
    assert shutdown_called


def test_monitor_settable_warning_threshold(monitor, mock_ina, dynamic_config):
    """Raising the threshold shuts down at a higher charge."""
    dynamic_config.data["battery_warning_threshold"] = 50
    shutdown_called = _shutdown_events(monitor)

    with patch.object(monitor, "_update"):
        for _ in range(DEFAULT_SHUTDOWN_CONSECUTIVE_READINGS):
            _run_monitor_with_ina(monitor, mock_ina, VOLTAGE_49_PERCENT, 500.0)

    assert monitor.data.battery_warning_threshold == 50
    assert shutdown_called


def test_monitor_above_warning_threshold_does_not_shut_down(
    monitor,
    mock_ina,
    dynamic_config,
):
    """Above the threshold on battery it keeps running."""
    dynamic_config.data["battery_warning_threshold"] = 5
    shutdown_called = _shutdown_events(monitor)

    with patch.object(monitor, "_update"):
        for _ in range(DEFAULT_SHUTDOWN_CONSECUTIVE_READINGS + 1):
            _run_monitor_with_ina(monitor, mock_ina, VOLTAGE_7_PERCENT, 500.0)

    assert not shutdown_called


def test_monitor_low_battery_with_external_power_does_not_shut_down(
    monitor,
    mock_ina,
):
    """Charging below the threshold is safe, so it stays on."""
    shutdown_called = _shutdown_events(monitor)

    with patch.object(monitor, "_update"):
        for _ in range(DEFAULT_SHUTDOWN_CONSECUTIVE_READINGS + 1):
            _run_monitor_with_ina(monitor, mock_ina, VOLTAGE_3_PERCENT, -400.0)

    assert monitor.data.charging is True
    assert not shutdown_called


# ---------------------------------------------------------------------------
# Start up below the warning threshold
# ---------------------------------------------------------------------------


def test_start_up_below_shutdown_level_while_charging_stays_on(
    monitor,
    mock_ina,
    caplog,
):
    """Restarted by power returning, the charging battery keeps it on."""
    shutdown_called = _shutdown_events(monitor)

    with patch.object(monitor, "_update"), caplog.at_level("INFO", "Red Reactor"):
        _run_monitor_with_ina(monitor, mock_ina, VOLTAGE_3_PERCENT, -400.0)

    assert "the battery is charging so staying on" in caplog.text
    assert not shutdown_called


def test_start_up_below_shutdown_level_on_battery_shuts_down(
    monitor,
    mock_ina,
    caplog,
):
    """Started without external power below the level, it shuts down again."""
    shutdown_called = _shutdown_events(monitor)

    with patch.object(monitor, "_update"), caplog.at_level("INFO", "Red Reactor"):
        for _ in range(DEFAULT_SHUTDOWN_CONSECUTIVE_READINGS):
            _run_monitor_with_ina(monitor, mock_ina, VOLTAGE_3_PERCENT, 500.0)

    assert "without external power" in caplog.text
    assert shutdown_called


def test_start_up_below_shutdown_level_not_charging_warns(
    monitor,
    mock_ina,
    caplog,
):
    """External power with no charge current is logged as a problem."""
    with patch.object(monitor, "_update"), caplog.at_level("INFO", "Red Reactor"):
        _run_monitor_with_ina(monitor, mock_ina, VOLTAGE_3_PERCENT, 5.0)

    assert "the battery is not charging" in caplog.text


def test_start_up_check_only_runs_once(monitor, mock_ina):
    """The start up check is for the first reading only."""
    with (
        patch.object(monitor, "_update"),
        patch.object(monitor, "_check_start_up_charge") as check,
    ):
        _run_monitor_with_ina(monitor, mock_ina)
        _run_monitor_with_ina(monitor, mock_ina)

    check.assert_called_once()


def test_start_up_above_shutdown_level_logs_nothing(monitor, mock_ina, caplog):
    """A normal start does not log a start up warning."""
    with patch.object(monitor, "_update"), caplog.at_level("INFO", "Red Reactor"):
        _run_monitor_with_ina(monitor, mock_ina, VOLTAGE_49_PERCENT, 500.0)

    assert "Started at" not in caplog.text


# ---------------------------------------------------------------------------
# Battery runtime limit
# ---------------------------------------------------------------------------


def test_runtime_limit_disabled_by_default(monitor, mock_ina):
    """With the default limit of 0, time on battery never shuts down."""
    shutdown_called = _shutdown_events(monitor)

    with (
        patch.object(monitor, "_update"),
        patch("redreactor.components.monitor.monitor.time.monotonic") as monotonic,
    ):
        monotonic.return_value = 0
        _run_monitor_with_ina(monitor, mock_ina, VOLTAGE_49_PERCENT, 500.0)
        monotonic.return_value = 24 * 60 * 60
        _run_monitor_with_ina(monitor, mock_ina, VOLTAGE_49_PERCENT, 500.0)

    assert not shutdown_called


def test_runtime_limit_shuts_down_after_limit(monitor, mock_ina, dynamic_config):
    """On battery for longer than the limit, it shuts down at any charge."""
    dynamic_config.data["battery_runtime_limit"] = 10
    shutdown_called = _shutdown_events(monitor)

    with (
        patch.object(monitor, "_update"),
        patch("redreactor.components.monitor.monitor.time.monotonic") as monotonic,
    ):
        monotonic.return_value = 1000
        _run_monitor_with_ina(monitor, mock_ina, VOLTAGE_49_PERCENT, 500.0)
        monotonic.return_value = 1000 + 9 * 60
        _run_monitor_with_ina(monitor, mock_ina, VOLTAGE_49_PERCENT, 500.0)
        assert not shutdown_called

        monotonic.return_value = 1000 + 10 * 60
        _run_monitor_with_ina(monitor, mock_ina, VOLTAGE_49_PERCENT, 500.0)

    assert shutdown_called


def test_runtime_limit_resets_when_power_returns(monitor, mock_ina, dynamic_config):
    """External power returning restarts the runtime count."""
    dynamic_config.data["battery_runtime_limit"] = 10
    shutdown_called = _shutdown_events(monitor)

    with (
        patch.object(monitor, "_update"),
        patch("redreactor.components.monitor.monitor.time.monotonic") as monotonic,
    ):
        monotonic.return_value = 0
        _run_monitor_with_ina(monitor, mock_ina, VOLTAGE_49_PERCENT, 500.0)
        monotonic.return_value = 9 * 60
        _run_monitor_with_ina(monitor, mock_ina, VOLTAGE_49_PERCENT, -50.0)
        monotonic.return_value = 10 * 60
        _run_monitor_with_ina(monitor, mock_ina, VOLTAGE_49_PERCENT, 500.0)
        monotonic.return_value = 15 * 60
        _run_monitor_with_ina(monitor, mock_ina, VOLTAGE_49_PERCENT, 500.0)

    assert not shutdown_called


# ---------------------------------------------------------------------------
# Published state and INA219 setup
# ---------------------------------------------------------------------------


def test_state_payload_includes_new_fields(monitor, mock_ina):
    """Power, charging and the runtime limit are published."""
    import json

    from redreactor.components.mqtt import MQTT

    published = {}
    MQTT.event.on(
        "publish",
        lambda topic, payload, **_: published.__setitem__(topic, payload),
    )
    mock_ina.power.return_value = 1234.0
    _run_monitor_with_ina(monitor, mock_ina, VOLTAGE_49_PERCENT, -50.0)
    monitor._update()

    state = json.loads(published["redreactor/redreactor/state"])
    assert state["power"] == 1.234
    assert state["charging"] == "ON"
    assert state["battery_runtime_limit"] == 0


def test_ina_uses_configured_bus(static_config, dynamic_config, mock_ina):
    """The I2C bus comes from the configuration rather than being fixed."""
    from redreactor.components.monitor.monitor import Monitor

    static_config["ina"]["bus"] = 3
    with patch(
        "redreactor.components.monitor.monitor.INA219",
        return_value=mock_ina,
    ) as ina_class:
        monitor = Monitor(static_config, dynamic_config)
    monitor.monitor_timer.stop()

    assert ina_class.call_args.kwargs["busnum"] == 3


def test_read_once_returns_a_reading(static_config, mock_ina):
    """`--check` reads the board once without starting the service."""
    from redreactor.components.monitor import read_once

    mock_ina.voltage.return_value = 4.1
    mock_ina.current.return_value = -120.0
    mock_ina.power.return_value = 492.0
    with patch(
        "redreactor.components.monitor.monitor.INA219",
        return_value=mock_ina,
    ):
        reading = read_once(static_config)

    assert reading == {
        "i2c_bus": 1,
        "i2c_address": "0x40",
        "voltage": 4.1,
        "current": -120.0,
        "power": 0.492,
        "charging": True,
    }


def test_read_once_exits_when_board_is_missing(static_config):
    """A missing board exits non-zero so the problem is obvious."""
    from redreactor.components.monitor import read_once

    with (
        patch(
            "redreactor.components.monitor.monitor.INA219",
            side_effect=OSError("No such device"),
        ),
        pytest.raises(SystemExit) as exit_info,
    ):
        read_once(static_config)

    assert exit_info.value.code == 1
