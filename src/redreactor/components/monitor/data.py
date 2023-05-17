"""Monitor Data file."""


from redreactor.const import (
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
    DEFAULT_BATTERY_VOLTAGE_MINIMUM,
    DEFAULT_BATTERY_WARNING_THRESHOLD,
    DEFAULT_REPORT_INTERVAL,
)


class MonitorData:
    """Monitor Data."""

    voltage: float
    current: float
    battery_level: float
    external_power: bool
    cpu_temperature: float | None
    cpu_stat: int | None
    battery_warning_threshold: int
    battery_voltage_minimum: float
    battery_voltage_maximum: float
    report_interval: int

    def __init__(  # noqa: PLR0913
        self,
        voltage: float = 0.0,
        current: float = 0.0,
        battery_level: float = 0.0,
        external_power: bool = True,  # noqa: FBT001, FBT002
        cpu_temperature: float = 0.0,
        cpu_stat: int = 0,
        battery_warning_threshold: int = DEFAULT_BATTERY_WARNING_THRESHOLD,
        battery_voltage_minimum: float = DEFAULT_BATTERY_VOLTAGE_MINIMUM,
        battery_voltage_maximum: float = DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
        report_interval: int = DEFAULT_REPORT_INTERVAL,
    ) -> None:
        """Initialise Monitor Data."""
        self.voltage = voltage
        self.current = current
        self.battery_level = battery_level
        self.external_power = external_power
        self.cpu_temperature = cpu_temperature
        self.cpu_stat = cpu_stat
        self.battery_warning_threshold = battery_warning_threshold
        self.battery_voltage_minimum = battery_voltage_minimum
        self.battery_voltage_maximum = battery_voltage_maximum
        self.report_interval = report_interval
