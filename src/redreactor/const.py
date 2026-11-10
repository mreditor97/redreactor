"""Constants used by Red Reactor components."""

DEFAULT_REPORT_INTERVAL = 30  # Seconds between data reporting
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
# Battery capacity in mAh, used to estimate the time remaining, 0 means not set
DEFAULT_BATTERY_CAPACITY = 0
# Battery internal resistance in milliohms, used to correct the voltage for the
# sag under load before working out the battery level, 0 turns it off. The
# default is the Samsung INR18650-35E datasheet's maximum initial AC impedance.
# The real resistance (holder, wiring, board) is usually higher, so this tends
# to under-correct, which keeps the level and low battery shutdown on the safe
# side rather than reporting more charge than there is.
DEFAULT_BATTERY_INTERNAL_RESISTANCE = 35.0
# Monitor readings averaged for the battery level, as brief current spikes make
# single readings jump. 6 readings at the default 5 second interval is 30 seconds
DEFAULT_BATTERY_AVERAGE_READINGS = 6
BATTERY_AVERAGE_READINGS_MAXIMUM = 100

DEFAULT_INA_I2C_ADDRESS = 0x40  # Red Reactor Default I2C Address
DEFAULT_INA_SHUNT_OHMS = 0.05  # Red Reactor Shunt Ohms
DEFAULT_INA_MAX_EXPECTED_AMPS = 5.5
DEFAULT_INA_MONITOR_INTERVAL = 5  # Second read time
DEFAULT_INA_I2C_BUS = 1  # I2C bus the Red Reactor is connected to
# Samples the INA219 averages in hardware for each bus and shunt reading. 1 is
# a single 12-bit sample (532 us), 128 takes 68.1 ms per reading
INA_ADC_SAMPLES = (1, 2, 4, 8, 16, 32, 64, 128)
DEFAULT_INA_ADC_SAMPLES = 1

# The settings that can be changed over MQTT and are kept in the dynamic
# configuration file: their type and default. The MonitorData attribute of the
# same name holds the value in use. The monitor interval and the readings
# averaged default to their static configuration values instead.
DYNAMIC_SETTINGS: dict[str, tuple[type[int] | type[float], int | float]] = {
    "report_interval": (int, DEFAULT_REPORT_INTERVAL),
    "battery_warning_threshold": (int, DEFAULT_BATTERY_WARNING_THRESHOLD),
    "battery_voltage_minimum": (float, DEFAULT_BATTERY_VOLTAGE_MINIMUM),
    "battery_voltage_maximum": (float, DEFAULT_BATTERY_VOLTAGE_MAXIMUM),
    "battery_capacity": (int, DEFAULT_BATTERY_CAPACITY),
    "monitor_interval": (float, DEFAULT_INA_MONITOR_INTERVAL),
    "average_readings": (int, DEFAULT_BATTERY_AVERAGE_READINGS),
    "shutdown_readings": (int, DEFAULT_SHUTDOWN_CONSECUTIVE_READINGS),
}

# The log file lives on the SD card, so cap its size
DEFAULT_LOG_MAX_BYTES = 1024 * 1024
DEFAULT_LOG_BACKUP_COUNT = 3

# Seconds to wait after Home Assistant comes online before resending the latest
# readings, so the entities exist when the state message arrives
HOMEASSISTANT_ONLINE_STATE_DELAY = 2.0
# Seconds added to twice the report interval for the Home Assistant expire
# after time, so one late or missed report doesn't mark the entities
# unavailable. Used when the configured expire after is shorter than that.
HOMEASSISTANT_EXPIRE_AFTER_MARGIN = 30
# Event types published on the power event topic, for Home Assistant automations
POWER_EVENT_POWER_LOST = "power_lost"
POWER_EVENT_POWER_RESTORED = "power_restored"
POWER_EVENT_LOW_BATTERY = "low_battery"
POWER_EVENT_SHUTDOWN_STARTED = "shutdown_started"
POWER_EVENT_TYPES = (
    POWER_EVENT_POWER_LOST,
    POWER_EVENT_POWER_RESTORED,
    POWER_EVENT_LOW_BATTERY,
    POWER_EVENT_SHUTDOWN_STARTED,
)
# Seconds to wait after asking Home Assistant to migrate the old per-entity
# discovery topics, before publishing the device discovery that replaces them
HOMEASSISTANT_MIGRATION_DELAY = 1.0
# Hours in a day, the battery time remaining is published in days
HOURS_PER_DAY = 24

# Largest MQTT command payload accepted, a setting is a single number
COMMAND_PAYLOAD_MAXIMUM = 64
# Seconds a shutdown or restart command may run before it is given up on
SYSTEM_COMMAND_TIMEOUT = 60

# INA219 reads in a row that must fail before the sensor is reported as having
# a problem, and the readings are sent as unknown instead of the last good ones
SENSOR_PROBLEM_READINGS = 3
# Battery level change, in percentage points, that is reported straight away
# instead of at the next report interval, 0 turns it off
DEFAULT_BATTERY_REPORT_LEVEL_CHANGE = 5
# Shortest time in seconds between reports sent for a change, so a charging
# state that flickers around 0 mA doesn't send a report on every reading
REPORT_ON_CHANGE_MINIMUM_INTERVAL = 10.0
# Dynamic configuration key of the last shutdown or restart, and its reasons
LAST_SHUTDOWN_KEY = "last_shutdown"
SHUTDOWN_REASON_LOW_BATTERY = "Low battery"
SHUTDOWN_REASON_SHUTDOWN_BUTTON = "Shutdown button"
SHUTDOWN_REASON_RESTART_BUTTON = "Restart button"
# Extra seconds, on top of two monitor intervals, a reading may take before the
# systemd watchdog stops being told the service is healthy
WATCHDOG_TICK_MARGIN = 30.0
