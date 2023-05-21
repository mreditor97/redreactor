"""Constants used by Red Reactor components."""

DEFAULT_REPORT_INTERVAL = 30  # Seconds between data reporting
DEFAULT_EXPIRE_INTERVAL = 120  # Seconds before Home Assistant invalidates received data
DEFAULT_BATTERY_WARNING_THRESHOLD = 10  # Percentage of charge remaining
DEFAULT_BATTERY_VOLTAGE_MINIMUM = 2.7  # Minimum battery voltage before shutting down
DEFAULT_BATTERY_VOLTAGE_MAXIMUM = 4.2  # Maximum battery voltage
DEFAULT_BATTERY_VOLTAGE_ERROR = DEFAULT_BATTERY_VOLTAGE_MAXIMUM + 0.05

DEFAULT_INA_I2C_ADDRESS = 0x40  # Red Reactor Default I2C Address
DEFAULT_INA_SHUNT_OHMS = 0.05  # Red Reactor Shunt Ohms
DEFAULT_INA_MAX_EXPECTED_AMPS = 5.5
DEFAULT_INA_MONITOR_INTERVAL = 5  # Second read time
