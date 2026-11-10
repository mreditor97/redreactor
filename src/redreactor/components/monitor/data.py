"""Monitor Data file."""

from __future__ import annotations

from typing import Any

from redreactor.const import (
    DEFAULT_BATTERY_AVERAGE_READINGS,
    DEFAULT_BATTERY_CAPACITY,
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
    DEFAULT_BATTERY_VOLTAGE_MINIMUM,
    DEFAULT_BATTERY_WARNING_THRESHOLD,
    DEFAULT_INA_MONITOR_INTERVAL,
    DEFAULT_REPORT_INTERVAL,
    DEFAULT_SHUTDOWN_CONSECUTIVE_READINGS,
)


class MonitorData:
    """Monitor Data."""

    voltage: float
    current: float
    power: float
    charging: bool
    battery_level: float
    external_power: bool
    cpu_temperature: float | None
    cpu_stat_raw: int | None
    cpu_stat_text: str | None
    battery_warning_threshold: int
    battery_voltage_minimum: float
    battery_voltage_maximum: float
    report_interval: int
    battery_capacity: int
    battery_time_remaining: float | None
    monitor_interval: float
    average_readings: int
    shutdown_readings: int
    # Set after several INA219 reads in a row have failed
    sensor_problem: bool
    # The last shutdown or restart this service started, from the dynamic
    # configuration: its reason, the battery voltage and the time
    last_shutdown: dict[str, Any] | None

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        voltage: float = 0.0,
        current: float = 0.0,
        power: float = 0.0,
        charging: bool = False,  # noqa: FBT001, FBT002
        battery_level: float = 0.0,
        external_power: bool = True,  # noqa: FBT001, FBT002
        cpu_temperature: float = 0.0,
        cpu_stat_raw: int = 0,
        cpu_stat_text: str = "OK",
        battery_warning_threshold: int = DEFAULT_BATTERY_WARNING_THRESHOLD,
        battery_voltage_minimum: float = DEFAULT_BATTERY_VOLTAGE_MINIMUM,
        battery_voltage_maximum: float = DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
        report_interval: int = DEFAULT_REPORT_INTERVAL,
        battery_capacity: int = DEFAULT_BATTERY_CAPACITY,
        battery_time_remaining: float | None = None,
        monitor_interval: float = DEFAULT_INA_MONITOR_INTERVAL,
        average_readings: int = DEFAULT_BATTERY_AVERAGE_READINGS,
        shutdown_readings: int = DEFAULT_SHUTDOWN_CONSECUTIVE_READINGS,
        sensor_problem: bool = False,  # noqa: FBT001, FBT002
        last_shutdown: dict[str, Any] | None = None,
    ) -> None:
        """Initialise Monitor Data."""
        self.voltage = voltage
        self.current = current
        self.power = power
        self.charging = charging
        self.battery_level = battery_level
        self.external_power = external_power
        self.cpu_temperature = cpu_temperature
        self.cpu_stat_raw = cpu_stat_raw
        self.cpu_stat_text = cpu_stat_text
        self.battery_warning_threshold = battery_warning_threshold
        self.battery_voltage_minimum = battery_voltage_minimum
        self.battery_voltage_maximum = battery_voltage_maximum
        self.report_interval = report_interval
        self.battery_capacity = battery_capacity
        self.battery_time_remaining = battery_time_remaining
        self.monitor_interval = monitor_interval
        self.average_readings = average_readings
        self.shutdown_readings = shutdown_readings
        self.sensor_problem = sensor_problem
        self.last_shutdown = last_shutdown
