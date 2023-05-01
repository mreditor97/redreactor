class MonitorData(dict):
    voltage: float | None
    current: float | None
    battery_level: float | None
    external_power: bool | None
    cpu_temperature: float | None
    cpu_stat: int | None
    battery_warning_threshold: int | None
    battery_voltage_minimum: float | None
    battery_voltage_maximum: float | None
    report_interval: int | None

    def __init__(
        self,
        voltage: float | None = None,
        current: float | None = None,
        battery_level: float | None = None,
        external_power: bool | None = None,
        cpu_temperature: float | None = None,
        cpu_stat: int | None = None,
        battery_warning_threshold: int | None = None,
        battery_voltage_minimum: float | None = None,
        battery_voltage_maximum: float | None = None,
        report_interval: int | None = None,
    ):
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
