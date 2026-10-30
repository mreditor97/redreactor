"""Constants used by Red Reactor components."""

DEFAULT_REPORT_INTERVAL = 30  # Seconds between data reporting
DEFAULT_EXPIRE_INTERVAL = 120  # Seconds before Home Assistant invalidates received data
DEFAULT_BATTERY_WARNING_THRESHOLD = 10  # Percentage of charge to shut down at
DEFAULT_BATTERY_VOLTAGE_MINIMUM = 2.9  # Minimum battery voltage before shutting down
DEFAULT_BATTERY_VOLTAGE_MAXIMUM = 4.2  # Maximum battery voltage (fully charged)
# Consecutive readings at or below the battery warning threshold needed before
# shutting down, so a brief voltage sag under load doesn't power the device off
DEFAULT_SHUTDOWN_CONSECUTIVE_READINGS = 3
# Subtracting this drop from the maximum avoids reporting 100% under load, where
# voltage sags slightly even when the battery is full.
DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP = 0.03
# Voltage more than this above the configured maximum indicates external power
# is connected. The headroom avoids false positives from measurement noise.
DEFAULT_BATTERY_VOLTAGE_HEADROOM = 0.05
# Minutes on battery before shutting down regardless of charge, 0 disables it
DEFAULT_BATTERY_RUNTIME_LIMIT = 0

DEFAULT_INA_I2C_ADDRESS = 0x40  # Red Reactor Default I2C Address
DEFAULT_INA_SHUNT_OHMS = 0.05  # Red Reactor Shunt Ohms
DEFAULT_INA_MAX_EXPECTED_AMPS = 5.5
DEFAULT_INA_MONITOR_INTERVAL = 5  # Second read time
DEFAULT_INA_I2C_BUS = 1  # I2C bus the Red Reactor is connected to

# The log file lives on the SD card, so cap its size
DEFAULT_LOG_MAX_BYTES = 1024 * 1024
DEFAULT_LOG_BACKUP_COUNT = 3
