"""Monitor Data file."""

from __future__ import annotations

from redreactor.const import (
    DEFAULT_BATTERY_CAPACITY,
    DEFAULT_BATTERY_INTERNAL_RESISTANCE,
    DEFAULT_BATTERY_RUNTIME_LIMIT,
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
    DEFAULT_BATTERY_VOLTAGE_MINIMUM,
    DEFAULT_BATTERY_WARNING_THRESHOLD,
    DEFAULT_REPORT_INTERVAL,
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
    battery_runtime_limit: int
    battery_capacity: int
    battery_internal_resistance: int
    battery_time_remaining: float | None

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
        battery_runtime_limit: int = DEFAULT_BATTERY_RUNTIME_LIMIT,
        battery_capacity: int = DEFAULT_BATTERY_CAPACITY,
        battery_internal_resistance: int = DEFAULT_BATTERY_INTERNAL_RESISTANCE,
        battery_time_remaining: float | None = None,
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
        self.battery_runtime_limit = battery_runtime_limit
        self.battery_capacity = battery_capacity
        self.battery_internal_resistance = battery_internal_resistance
        self.battery_time_remaining = battery_time_remaining
