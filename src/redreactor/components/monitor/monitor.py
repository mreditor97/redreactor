"""Monitor module."""

from __future__ import annotations

import json
import logging
import sys
import time
from threading import Lock, RLock
from typing import TYPE_CHECKING, Any

from redreactor.components.monitor.data import MonitorData
from redreactor.components.mqtt import MQTT
from redreactor.const import (
    DEFAULT_BATTERY_AVERAGE_READINGS,
    DEFAULT_BATTERY_INTERNAL_RESISTANCE,
    DEFAULT_BATTERY_REPORT_LEVEL_CHANGE,
    DEFAULT_BATTERY_VOLTAGE_HEADROOM,
    DEFAULT_SHUTDOWN_CONSECUTIVE_READINGS,
    DYNAMIC_SETTINGS,
    POWER_EVENT_LOW_BATTERY,
    POWER_EVENT_POWER_LOST,
    POWER_EVENT_POWER_RESTORED,
    REPORT_ON_CHANGE_MINIMUM_INTERVAL,
    SENSOR_PROBLEM_READINGS,
    WATCHDOG_TICK_MARGIN,
)
from redreactor.helpers import battery
from redreactor.helpers.cpu_utils import (
    FREQ_CAPPED_BIT,
    SOFT_TEMP_LIMIT_BIT,
    THROTTLED_BIT,
    UNDER_VOLTAGE_BIT,
    read_cpu_stat,
    read_cpu_temperature,
)
from redreactor.helpers.emitter import EventEmitter
from redreactor.helpers.ina219 import INA219, DeviceRangeError
from redreactor.helpers.repeater import RepeatTimer
from redreactor.helpers.topics import Topics, binary_payload

if TYPE_CHECKING:
    from paho.mqtt.client import Client

    from redreactor.configuration import DynamicConfiguration


# Throttling bitmask bits for the under-voltage and throttled binary sensors.
# Throttled covers every way the CPU is slowed: frequency capped, throttled and
# the soft temperature limit. Only the current state bits are used, not the
# "has occurred since boot" history bits.
UNDER_VOLTAGE_MASK = 1 << UNDER_VOLTAGE_BIT
THROTTLED_MASK = (
    (1 << FREQ_CAPPED_BIT) | (1 << THROTTLED_BIT) | (1 << SOFT_TEMP_LIMIT_BIT)
)


# INA219 ADC settings, the values of the configuration register's bus and
# shunt ADC fields (INA219.ADC_12BIT and INA219.ADC_2SAMP)
INA_ADC_12BIT = 3
INA_ADC_2SAMP = 9


def ina_adc_setting(samples: int) -> int:
    """Return the INA219 ADC setting that averages this many samples.

    1 is the library's single 12-bit sample (ADC_12BIT = 3). Averaging 2 to
    128 samples are ADC_2SAMP (9) to ADC_128SAMP (15), one step per doubling.
    """
    if samples <= 1:
        return INA_ADC_12BIT
    return INA_ADC_2SAMP + samples.bit_length() - 2


def create_ina(ina_configuration: dict[str, Any]) -> INA219:
    """Connect to the INA219 and set it up as the configuration says."""
    ina = INA219(
        shunt_ohms=ina_configuration["shunt_ohms"],
        max_expected_amps=ina_configuration["max_expected_amps"],
        address=ina_configuration["address"],
        busnum=int(ina_configuration["bus"]),
        log_level=logging.ERROR,
    )
    adc = ina_adc_setting(int(ina_configuration["adc_samples"]))
    ina.configure(voltage_range=ina.RANGE_16V, bus_adc=adc, shunt_adc=adc)
    return ina


def published_current(current: float) -> float:
    """Return the INA219 current (mA) the way it is published.

    The INA219 reads the discharge current as positive. It is published the
    other way round, negative while the battery is discharging and positive
    while it is charging. Adding 0.0 turns -0.0 (a zero reading negated) into
    0.0.
    """
    return round(-current, 4) + 0.0


def read_once(static_configuration: dict[str, Any]) -> dict[str, Any]:
    """Read the Red Reactor once, without starting the monitoring service.

    Used by `--check` to confirm the I2C setup. Exits with a non-zero code if
    the INA219 can't be reached.
    """
    ina_configuration = static_configuration["ina"]
    try:
        ina = create_ina(ina_configuration)
        voltage = ina.voltage()
        current = ina.current()
        return {
            "i2c_bus": int(ina_configuration["bus"]),
            "i2c_address": hex(ina_configuration["address"]),
            "voltage": round(voltage, 3),
            "current": published_current(current),
            "power": round(abs(voltage * current) / 1000, 3),
            "charging": current < 0,
        }
    except (OSError, ModuleNotFoundError, DeviceRangeError):
        logging.getLogger("Red Reactor").exception(
            "Unable to read the Red Reactor on I2C bus %s at address %s",
            ina_configuration["bus"],
            hex(ina_configuration["address"]),
        )
        sys.exit(1)


class Monitor:
    """Monitor module.

    Used to monitor the state of the Red Reactor
    """

    logger = logging.getLogger("Red Reactor")

    event: EventEmitter

    _static_configuration: dict[str, Any]
    _dynamic_configuration: DynamicConfiguration

    # Adds default values into the Monitor Data dict
    data: MonitorData

    # Consecutive monitor readings at or below the warning threshold without
    # external power
    _empty_readings: int = 0

    # Whether the first reading after start up has been checked
    _start_up_checked: bool = False

    # Whether the low battery shutdown has been started
    _shutdown_emitted: bool = False

    # Set when shutting down or restarting, nothing more is published so the
    # retained status stays offline
    _stopped: bool = False

    # Whether the INA219 has been read at least once since start up
    _has_reading: bool = False

    # Set when MQTT connects before the first reading, so that reading is
    # reported as soon as it is taken
    _report_pending: bool = False

    # Recent readings averaged for the battery level
    _battery_readings: battery.ReadingAverage

    # Timers
    monitor_timer: RepeatTimer  # Runs Monitoring calculations
    report_timer: RepeatTimer  # Pushes updates to MQTT

    def __init__(
        self,
        static_configuration: Any,
        dynamic_configuration: DynamicConfiguration,
    ) -> None:
        """Initialise Monitor object."""
        self.event = EventEmitter()
        # The other values start at MonitorData's defaults, the settings are
        # read from the dynamic configuration below
        self.data = MonitorData(battery_level=100)
        self._static_configuration = static_configuration
        self._dynamic_configuration = dynamic_configuration
        self._topics = Topics.from_configuration(static_configuration)
        battery_configuration = static_configuration.get("battery", {})
        self._monitor_interval = float(static_configuration["ina"]["monitor_interval"])
        self._battery_readings = battery.ReadingAverage(
            int(
                battery_configuration.get(
                    "average_readings",
                    DEFAULT_BATTERY_AVERAGE_READINGS,
                ),
            ),
        )
        # Low battery readings in a row needed before shutting down
        self._shutdown_readings = int(
            battery_configuration.get(
                "shutdown_readings",
                DEFAULT_SHUTDOWN_CONSECUTIVE_READINGS,
            ),
        )
        self._has_reading = False
        self._read_failures = 0
        # Set after several INA219 reads in a row have failed, the readings
        # are then sent as unknown rather than the last good ones
        self._sensor_problem = False
        self._report_pending = False
        self._shutdown_emitted = False
        self._stopped = False
        # The battery level and charging state last reported, and when, for
        # reporting a change straight away
        self._reported_level: float | None = None
        self._reported_charging: bool | None = None
        self._reported_at = 0.0
        # When the last reading finished, for the systemd watchdog
        self._last_tick = time.monotonic()
        # Guards the two flags above, which the MQTT thread and the monitor
        # timer thread both use
        self._report_lock = Lock()
        # Held while a reading is taken and while a report is put together,
        # which happen on different threads, so a report never mixes values
        # from two readings (such as a new voltage with the old level)
        self._data_lock = RLock()

        # Register Dynamic Configuration update listener
        self._dynamic_configuration.event.on(event_name="write", function=self._update)

        # Register MQTT on connect listener
        MQTT.event.on(event_name="on_connect", function=self._mqtt_on_connect)

        # Resend the latest readings when Home Assistant restarts, rather than
        # leaving them unknown until the next report
        MQTT.event.on(event_name="homeassistant_online", function=self._update)

        self.logger.info("Initiating battery monitor")

        # Configure the report timer, gets started on MQTT connect
        self.report_timer = RepeatTimer(
            self.data.report_interval,
            self._update,
        )

        # Update Dynamic Configuration values to there latest values
        self._update_dynamic_configuration()

        # Setup the INA219
        try:
            ina = create_ina(static_configuration["ina"])
        except (OSError, ModuleNotFoundError):
            self.logger.exception("Unable to connect to the Red Reactor")

            # Exit the program, non-zero so a supervisor can retry
            sys.exit(1)

        # Configure the monitor timer, start's as soon as possible
        self.monitor_timer = RepeatTimer(
            self._monitor_interval,
            self._monitor,
            ina=ina,
        )
        self.monitor_timer.start()

    def is_healthy(self) -> bool:
        """Return whether the readings are still being taken.

        Used by the systemd watchdog. Readings that stop because the service
        is shutting down or restarting are expected, so that counts as healthy.
        """
        if self._stopped:
            return True
        allowed = 2 * self._monitor_interval + WATCHDOG_TICK_MARGIN
        return time.monotonic() - self._last_tick <= allowed

    def _monitor(self, ina: INA219) -> None:
        """Monitor INA Thread Loop.

        Gets called every 'monitor_interval'. The shutdown is started outside
        the data lock, as it waits for the offline status to be delivered and
        for the shutdown command to run.
        """
        self.logger.debug("Monitoring thread has been started")

        with self._data_lock:
            shutdown = self._take_reading(ina)
            self._last_tick = time.monotonic()
            start_shutdown = shutdown and not self._shutdown_emitted
            if start_shutdown:
                self._shutdown_emitted = True

        # Shutdown system, once, the readings carry on while it runs
        if start_shutdown:
            self.logger.warning(
                "Forcing system shutdown, going offline with %fV",
                round(self.data.voltage, 2),
            )

            # Emit the shutdown event
            self.event.emit("shutdown")

    def _take_reading(self, ina: INA219) -> bool:
        """Read the INA219 and decide on the power state.

        Returns whether the battery is low enough to shut down.
        """
        # The dynamic configuration isn't read again here: a change from MQTT
        # emits `write`, which runs `_update` and reads it straight away.
        if ina and not self._read_ina(ina):
            # Skip this reading, rather than making a decision on stale values
            return False

        # Voltage above the nominal maximum indicates external power is present
        # (e.g. charger connected but INA219 current read was noisy/stale).
        # Checked before the warning and shutdown decisions so they use it.
        if (
            self.data.voltage
            > self.data.battery_voltage_maximum + DEFAULT_BATTERY_VOLTAGE_HEADROOM
        ):
            # Power detected from the voltage, published straight away
            self._set_external_power(external_power=True)

        if ina:
            if not self._start_up_checked:
                self._start_up_checked = True
                self._check_start_up_charge()
            self._report_if_pending()
            self._report_if_changed()

        return self._check_low_battery()

    def _read_ina(self, ina: INA219) -> bool:
        """Read the voltage and current, and work out the readings from them.

        Returns False when the INA219 couldn't be read, so this reading is
        skipped and the next tick tries again.
        """
        try:
            self.data.voltage = ina.voltage()
            self.data.current = ina.current()
            self.data.battery_level = self._average_battery_level(
                self.data.voltage,
                self.data.current,
            )
        except DeviceRangeError as error:
            self._current_out_of_range(error)
            return True
        except ZeroDivisionError:
            self.logger.exception(
                "Minimum Voltage %fV and Maximum Voltage %fV difference is equal to 0",  # noqa: E501
                self.data.battery_voltage_minimum,
                self.data.battery_voltage_maximum,
            )
            return True
        except OSError as error:
            # An I2C read can fail with a loose connection or a busy bus
            self._reading_failed(error)
            return False

        # Worked out here rather than read from the INA219, as power() reads
        # the overflow flag and the power register, two more I2C reads for
        # what the chip calculates the same way. Volts x milliamps / 1000 is
        # watts, always positive like the chip's own power register
        self.data.power = abs(self.data.voltage * self.data.current) / 1000
        # A negative current means the battery is being charged
        self.data.charging = self.data.current < 0
        self._reading_worked()
        # INA219 current sign convention on the Red Reactor:
        #   > 10 mA  -- discharging (no external power)
        #   0-10 mA  -- float charge (battery full, power present)
        #   negative -- actively charging (power just reconnected)
        if self.data.current > 10:
            # Power removed
            self._set_external_power(external_power=False)
        else:
            # Power restored, the battery is floating or actively charging
            self._set_external_power(external_power=True)
        return True

    def _current_out_of_range(self, error: DeviceRangeError) -> None:
        """Handle a current above what the INA219 can measure.

        The device is still running, so stay online and publish straight away,
        reporting the current as the configured maximum. No external power is
        assumed, so the device still shuts down on a low voltage reading.
        """
        self.logger.error("Battery current range error", exc_info=error)
        self._set_external_power(external_power=False, update=False)
        self.data.charging = False
        self.data.current = (
            float(self._static_configuration["ina"]["max_expected_amps"]) * 1000
        )
        # power() would raise the same error, so estimate it from the voltage
        # and the capped current rather than keep a stale value
        self.data.power = self.data.voltage * self.data.current / 1000
        # The real current is unknown, so the voltage can't be corrected for
        # the load
        self.data.battery_level = self._average_battery_level(
            self.data.voltage,
            0.0,
        )
        self._update()

    def _check_low_battery(self) -> bool:
        """Count low battery readings, returning whether to shut down.

        Only counted without external power. The shutdown needs
        `battery.shutdown_readings` low readings in a row, so one bad reading
        can't shut the device down.
        """
        if (
            self.data.battery_level > float(self.data.battery_warning_threshold)
            or self.data.external_power
        ):
            self._empty_readings = 0
            return False

        # Publish immediately so Home Assistant reflects the warning without
        # waiting for the next scheduled report_interval tick.
        self._update()

        self._empty_readings += 1
        if self._empty_readings == 1:
            self.publish_event(POWER_EVENT_LOW_BATTERY)
        shutdown = self._empty_readings >= self._shutdown_readings
        if not shutdown:
            self.logger.warning(
                "Battery at %i%% (%fV), at or below the %i%% warning threshold, "
                "reading %i of %i before shutdown",
                self.data.battery_level,
                round(self.data.voltage, 2),
                self.data.battery_warning_threshold,
                self._empty_readings,
                self._shutdown_readings,
            )
        return shutdown

    def _reading_failed(self, error: OSError) -> None:
        """Count a failed read, sending the readings as unknown after several.

        Logged once until a read works again, so a lasting fault doesn't flood
        the log.
        """
        self._read_failures += 1
        if self._read_failures == 1:
            self.logger.error(  # noqa: TRY400
                "Unable to read the Red Reactor (%s), retrying every %ss",
                error,
                self._monitor_interval,
            )
        if self._read_failures >= SENSOR_PROBLEM_READINGS and not (
            self._sensor_problem
        ):
            # Send the readings as unknown, rather than leaving the last good
            # ones in Home Assistant as if they were current
            self.logger.error(  # noqa: TRY400
                "%i Red Reactor readings in a row have failed, sending the "
                "readings as unknown",
                self._read_failures,
            )
            self._sensor_problem = True
            self._update()

    def _reading_worked(self) -> None:
        """Clear the failed reads after a good read, reporting straight away."""
        if not self._read_failures:
            return
        self.logger.warning(
            "Reading the Red Reactor again, after %i failed readings",
            self._read_failures,
        )
        self._read_failures = 0
        if self._sensor_problem:
            self._sensor_problem = False
            self._update()

    def _set_external_power(
        self,
        *,
        external_power: bool,
        update: bool = True,
    ) -> None:
        """Record the external power state, publishing it when it changes.

        A change after the first reading is also sent as a power lost or power
        restored event. The first reading only sets the starting state, which
        isn't a change of power.
        """
        if self.data.external_power == external_power:
            return

        self.data.external_power = external_power

        if self._has_reading:
            self.publish_event(
                (
                    POWER_EVENT_POWER_RESTORED
                    if external_power
                    else POWER_EVENT_POWER_LOST
                ),
            )

        if update:
            self._update()

    def publish_event(self, event_type: str) -> None:
        """Publish a power event, such as power lost, for Home Assistant.

        Events aren't retained, an old one replayed on reconnect would trigger
        automations again.
        """
        if self._stopped:
            return

        self.logger.info("Power event: %s", event_type)

        MQTT.event.emit(
            event_name="publish",
            topic=self._topics.event,
            payload=json.dumps({"event_type": event_type}),
            qos=1,
            retain=False,
        )

    def _report_if_pending(self) -> None:
        """Report the first reading if MQTT connected before it was taken."""
        with self._report_lock:
            self._has_reading = True
            pending = self._report_pending
            self._report_pending = False

        if pending:
            self._update()

    def _report_if_changed(self) -> None:
        """Report straight away when the level or charging state has changed.

        The battery level must have moved by `battery.report_level_change`
        percentage points since the last report. The report interval carries
        on as a heartbeat. Nothing is sent before the first report, or more
        often than every REPORT_ON_CHANGE_MINIMUM_INTERVAL seconds.
        """
        if self._reported_level is None:
            return
        if time.monotonic() - self._reported_at < REPORT_ON_CHANGE_MINIMUM_INTERVAL:
            return

        level_change = float(
            self._static_configuration.get("battery", {}).get(
                "report_level_change",
                DEFAULT_BATTERY_REPORT_LEVEL_CHANGE,
            ),
        )
        level_changed = (
            level_change > 0
            and abs(self.data.battery_level - self._reported_level) >= level_change
        )
        if level_changed or self.data.charging != self._reported_charging:
            self.logger.debug("Battery level or charging changed, reporting it")
            self._update()

    def _check_start_up_charge(self) -> None:
        """Check the battery is charging if it starts below the warning threshold.

        After a low battery shutdown the device is usually started again by
        external power returning, with the battery still below the shutdown
        level. That is safe while it charges. Without external power it would
        drain the battery further, so the usual shutdown check (which only
        runs without external power) shuts it down again. External power with
        no charge current means the battery isn't recovering, which is logged
        so it can be looked into.
        """
        if self.data.battery_level > self.data.battery_warning_threshold:
            return

        if not self.data.external_power:
            self.logger.warning(
                "Started at %i%%, below the %i%% warning threshold without external "
                "power, shutting down again unless power is connected",
                self.data.battery_level,
                self.data.battery_warning_threshold,
            )
        elif self.data.charging:
            self.logger.info(
                "Started at %i%%, below the %i%% warning threshold, the battery is "
                "charging so staying on",
                self.data.battery_level,
                self.data.battery_warning_threshold,
            )
        else:
            self.logger.warning(
                "Started at %i%%, below the %i%% warning threshold, external power is "
                "connected but the battery is not charging (%fmA)",
                self.data.battery_level,
                self.data.battery_warning_threshold,
                self.data.current,
            )

    def _average_battery_level(self, voltage: float, current: float) -> int:
        """Add a reading and work out the battery level from the recent average.

        The level uses the average of the last `battery.average_readings`
        readings, see `battery.ReadingAverage`.
        """
        return self._calculate_battery_level(
            *self._battery_readings.add(voltage, current),
        )

    def _calculate_battery_level(self, voltage: float, current: float = 0.0) -> int:
        """Work out the battery level with the settings in use."""
        battery_configuration = self._static_configuration.get("battery", {})
        return battery.battery_level(
            voltage,
            current,
            internal_resistance=float(
                battery_configuration.get(
                    "internal_resistance",
                    DEFAULT_BATTERY_INTERNAL_RESISTANCE,
                ),
            ),
            curve=battery_configuration.get("curve"),
            minimum=self.data.battery_voltage_minimum,
            maximum=self.data.battery_voltage_maximum,
        )

    def _calculate_battery_time_remaining(self) -> float | None:
        """Estimate the days left on battery before the low battery shutdown."""
        return battery.time_remaining(
            capacity=self.data.battery_capacity,
            level=self.data.battery_level,
            shutdown_level=self.data.battery_warning_threshold,
            current=self.data.current,
            external_power=self.data.external_power,
        )

    def _update_cpu_information(self) -> None:
        """Update CPU information, including temperature and throttling."""
        try:
            # Temperature
            self.data.cpu_temperature = read_cpu_temperature()

            # Throttled state
            self.data.cpu_stat_raw = read_cpu_stat()

        except Exception:
            self.logger.exception("Failed to read CPU Information")
            self.data.cpu_temperature = None
            self.data.cpu_stat_raw = None

    def stop(self) -> None:
        """Stop reading and publishing, before a shutdown or restart.

        Otherwise a reading taken while the device shuts down would publish the
        online status again after the offline one.
        """
        self._stopped = True
        self.monitor_timer.stop()
        self.report_timer.stop()

    def _update(self) -> None:
        """Pushes the latest data to Monitor endpoint."""
        if self._stopped:
            return
        with self._data_lock:
            # Force a update of the dynamic configuration values
            self._update_dynamic_configuration()

            # Update CPU information before publishing info
            self._update_cpu_information()

            self.data.battery_time_remaining = self._calculate_battery_time_remaining()

            payload = json.dumps(self._state_payload())
            self._reported_level = self.data.battery_level
            self._reported_charging = self.data.charging
            self._reported_at = time.monotonic()

        # The retained online status isn't sent with every report. MQTT sends
        # it on every connect, and the Last Will replaces it with offline if
        # this device drops off, so sending it again would change nothing.

        # Publish latest data to state endpoint
        MQTT.event.emit(
            event_name="publish",
            topic=self._topics.state,
            payload=payload,
            # Retained so Home Assistant gets the latest readings as soon as
            # it subscribes, after discovery or its own restart, instead of
            # waiting for the next report. The status topic's Last Will marks
            # them unavailable if this device drops off.
            retain=True,
        )

    def _state_payload(self) -> dict[str, Any]:
        """Return the state message, keyed by each field's configured name."""
        fields = self._static_configuration["fields"]
        values: dict[str, Any] = {
            "voltage": round(self.data.voltage, 3),
            "current": published_current(self.data.current),
            "power": round(self.data.power, 3),
            "battery_level": self.data.battery_level,
            "external_power": binary_payload(
                fields["external_power"],
                self.data.external_power,
            ),
            "charging": binary_payload(fields["charging"], self.data.charging),
            "cpu_temperature": self.data.cpu_temperature,
            "under_voltage": self._cpu_stat_payload(
                "under_voltage",
                UNDER_VOLTAGE_MASK,
            ),
            "throttled": self._cpu_stat_payload("throttled", THROTTLED_MASK),
            "battery_warning_threshold": self.data.battery_warning_threshold,
            "battery_voltage_minimum": self.data.battery_voltage_minimum,
            "battery_voltage_maximum": self.data.battery_voltage_maximum,
            "report_interval": self.data.report_interval,
            "battery_capacity": self.data.battery_capacity,
            "battery_time_remaining": self.data.battery_time_remaining,
        }
        if self._sensor_problem:
            # The INA219 can't be read, so these would be the last good values
            for key in (
                "voltage",
                "current",
                "power",
                "battery_level",
                "external_power",
                "charging",
                "battery_time_remaining",
            ):
                values[key] = None
        return {str(fields[key]["name"]): value for key, value in values.items()}

    def _cpu_stat_payload(self, field: str, mask: int) -> str | None:
        """Return a binary sensor payload for bits of the throttling bitmask.

        None (unknown in Home Assistant) when the bitmask couldn't be read.
        """
        if self.data.cpu_stat_raw is None:
            return None

        return binary_payload(
            self._static_configuration["fields"][field],
            bool(self.data.cpu_stat_raw & mask),
        )

    def _update_dynamic_configuration(self) -> None:
        """Update Dynamic Configuration.

        This uses a event hook back to the Dynamic Configuration to update the file.
        The dynamic configuration is keyed by field key, not by the configurable
        field name used for MQTT topics and payloads.
        """
        for key, (kind, _) in DYNAMIC_SETTINGS.items():
            setattr(self.data, key, kind(self._dynamic_configuration.data[key]))

        if self.report_timer:
            # Apply the new report interval straight away, rather than after
            # the tick that is already waiting on the old interval
            self.report_timer.set_interval(self.data.report_interval)

    def _mqtt_on_connect(
        self,
        _client: Client,
        _userdata: Any,
        _flags: Any,
        _reason_code: Any,
        _properties: Any = None,
    ) -> None:
        """On MQTT Connect.

        Report straight away, or as soon as the first reading is taken if it
        hasn't been yet, rather than waiting a whole report interval. Then
        (re)start the report timer so the next report follows a full interval
        after this one, including after a reconnect.
        """
        with self._report_lock:
            report_now = self._has_reading
            self._report_pending = not report_now

        if report_now:
            self._update()

        self.report_timer.stop()
        self.report_timer.start()
