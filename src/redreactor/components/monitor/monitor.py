"""Monitor module."""

from __future__ import annotations

import json
import logging
import sys
from collections import deque
from itertools import pairwise
from threading import Lock
from typing import TYPE_CHECKING, Any

from ina219 import INA219, DeviceRangeError

from redreactor.components.monitor.data import MonitorData
from redreactor.components.mqtt import MQTT
from redreactor.const import (
    DEFAULT_BATTERY_AVERAGE_READINGS,
    DEFAULT_BATTERY_INTERNAL_RESISTANCE,
    DEFAULT_BATTERY_VOLTAGE_HEADROOM,
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP,
    DEFAULT_BATTERY_VOLTAGE_MINIMUM,
    DEFAULT_BATTERY_WARNING_THRESHOLD,
    DEFAULT_REPORT_INTERVAL,
    DEFAULT_SHUTDOWN_CONSECUTIVE_READINGS,
    HOURS_PER_DAY,
    POWER_EVENT_LOW_BATTERY,
    POWER_EVENT_POWER_LOST,
    POWER_EVENT_POWER_RESTORED,
)
from redreactor.helpers.cpu_utils import (
    FREQ_CAPPED_BIT,
    SOFT_TEMP_LIMIT_BIT,
    THROTTLED_BIT,
    UNDER_VOLTAGE_BIT,
    decode_cpu_stat_text,
    read_cpu_stat,
    read_cpu_temperature,
)
from redreactor.helpers.emitter import EventEmitter
from redreactor.helpers.repeater import RepeatTimer

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


def read_once(static_configuration: dict[str, Any]) -> dict[str, Any]:
    """Read the Red Reactor once, without starting the monitoring service.

    Used by `--check` to confirm the I2C setup. Exits with a non-zero code if
    the INA219 can't be reached.
    """
    ina_configuration = static_configuration["ina"]
    try:
        ina = INA219(
            shunt_ohms=ina_configuration["shunt_ohms"],
            max_expected_amps=ina_configuration["max_expected_amps"],
            address=ina_configuration["address"],
            busnum=int(ina_configuration["bus"]),
            log_level=logging.ERROR,
        )
        ina.configure(voltage_range=ina.RANGE_16V)
        current = ina.current()
        return {
            "i2c_bus": int(ina_configuration["bus"]),
            "i2c_address": hex(ina_configuration["address"]),
            "voltage": round(ina.voltage(), 3),
            # Published negative while discharging, positive while charging.
            # Adding 0.0 turns -0.0 (a zero reading negated) into 0.0
            "current": round(-current, 4) + 0.0,
            "power": round(ina.power() / 1000, 3),
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

    # Recent (voltage, current) readings averaged for the battery level
    _battery_readings: deque[tuple[float, float]]

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
        self.data = MonitorData(
            voltage=0.0,
            current=0.0,
            battery_level=100,
            external_power=True,
            cpu_temperature=0.0,
            cpu_stat_raw=0,
            cpu_stat_text="OK",
            battery_warning_threshold=DEFAULT_BATTERY_WARNING_THRESHOLD,
            battery_voltage_minimum=DEFAULT_BATTERY_VOLTAGE_MINIMUM,
            battery_voltage_maximum=DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
            report_interval=DEFAULT_REPORT_INTERVAL,
        )
        self._static_configuration = static_configuration
        self._dynamic_configuration = dynamic_configuration
        self._battery_readings = deque(
            maxlen=int(
                static_configuration.get("battery", {}).get(
                    "average_readings",
                    DEFAULT_BATTERY_AVERAGE_READINGS,
                ),
            ),
        )
        self._has_reading = False
        self._report_pending = False
        self._shutdown_emitted = False
        self._stopped = False
        # Guards the two flags above, which the MQTT thread and the monitor
        # timer thread both use
        self._report_lock = Lock()

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
        ina: INA219 | None = None
        try:
            ina = INA219(
                shunt_ohms=static_configuration["ina"]["shunt_ohms"],
                max_expected_amps=static_configuration["ina"]["max_expected_amps"],
                address=static_configuration["ina"]["address"],
                busnum=int(static_configuration["ina"]["bus"]),
                log_level=logging.ERROR,
            )
            ina.configure(voltage_range=ina.RANGE_16V)
        except (OSError, ModuleNotFoundError):
            self.logger.exception("Unable to connect to the Red Reactor")

            # Exit the program, non-zero so a supervisor can retry
            sys.exit(1)

        # Configure the monitor timer, start's as soon as possible
        self.monitor_timer = RepeatTimer(
            float(self._static_configuration["ina"]["monitor_interval"]),
            self._monitor,
            ina=ina,
        )
        self.monitor_timer.start()

    def _monitor(self, ina: INA219) -> None:  # noqa: C901, PLR0912, PLR0915
        """Monitor INA Thread Loop.

        Gets called every 'monitor_interval'.
        """
        self.logger.debug("Monitoring thread has been started")

        # Update the Dynamic Configuration to ensure the calculations will be based correctly off the changeable values # noqa: E501
        self._update_dynamic_configuration()

        shutdown: bool = False

        if ina:
            try:
                self.data.voltage = ina.voltage()
                self.data.current = ina.current()
                self.data.battery_level = self._average_battery_level(
                    self.data.voltage,
                    self.data.current,
                )
                # pi-ina219 reports milliwatts, Home Assistant is sent watts
                self.data.power = ina.power() / 1000
                # A negative current means the battery is being charged
                self.data.charging = self.data.current < 0
            except DeviceRangeError:
                # The current is above what the INA219 can measure. The device
                # is still running, so stay online and publish straight away,
                # reporting the current as the configured maximum.
                # Assume no external power so the device will still shutdown on a low voltage reading # noqa: E501
                self.logger.exception("Battery current range error")
                self._set_external_power(external_power=False, update=False)
                self.data.charging = False
                self.data.current = (
                    float(self._static_configuration["ina"]["max_expected_amps"]) * 1000
                )
                # power() would raise the same error, so estimate it from the
                # voltage and the capped current rather than keep a stale value
                self.data.power = self.data.voltage * self.data.current / 1000
                # The real current is unknown, so the voltage can't be
                # corrected for the load
                self.data.battery_level = self._average_battery_level(
                    self.data.voltage,
                    0.0,
                )
                self._update()
            except ZeroDivisionError:
                self.logger.exception(
                    "Minimum Voltage %fV and Maximum Voltage %fV difference is equal to 0",  # noqa: E501
                    self.data.battery_voltage_minimum,
                    self.data.battery_voltage_maximum,
                )
            else:
                # INA219 current sign convention on the Red Reactor:
                #   > 10 mA  -- discharging (no external power)
                #   0-10 mA  -- float charge (battery full, power present)
                #   negative -- actively charging (power just reconnected)
                if self.data.current > 10:
                    # Power removed
                    self._set_external_power(external_power=False)
                else:
                    # Power restored, the battery is floating (0-10 mA) or
                    # actively charging (negative)
                    self._set_external_power(external_power=True)

        # Voltage above the nominal maximum indicates external power is present
        # (e.g. charger connected but INA219 current read was noisy/stale).
        # Checked before the warning and shutdown decisions so they use it.
        if (
            self.data.voltage
            > self.data.battery_voltage_maximum + DEFAULT_BATTERY_VOLTAGE_HEADROOM
        ):
            # Power detected from the voltage, published straight away
            self._set_external_power(external_power=True)

        if ina and not self._start_up_checked:
            self._start_up_checked = True
            self._check_start_up_charge()

        if ina:
            self._report_if_pending()

        if (
            self.data.battery_level <= float(self.data.battery_warning_threshold)
            and not self.data.external_power
        ):
            # Publish immediately so Home Assistant reflects the warning without
            # waiting for the next scheduled report_interval tick.
            self._update()

            self._empty_readings += 1
            if self._empty_readings == 1:
                self.publish_event(POWER_EVENT_LOW_BATTERY)
            shutdown = self._empty_readings >= DEFAULT_SHUTDOWN_CONSECUTIVE_READINGS
            if not shutdown:
                self.logger.warning(
                    "Battery at %i%% (%fV), at or below the %i%% warning threshold, "
                    "reading %i of %i before shutdown",
                    self.data.battery_level,
                    round(self.data.voltage, 2),
                    self.data.battery_warning_threshold,
                    self._empty_readings,
                    DEFAULT_SHUTDOWN_CONSECUTIVE_READINGS,
                )
        else:
            self._empty_readings = 0

        # Shutdown system, once, the readings carry on while it runs
        if shutdown and not self._shutdown_emitted:
            self._shutdown_emitted = True
            self.logger.warning(
                "Forcing system shutdown, going offline with %fV",
                round(self.data.voltage, 2),
            )

            # Emit the shutdown event
            self.event.emit("shutdown")

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
            topic=f"{self._static_configuration['mqtt']['base_topic']}/{self._static_configuration['hostname']['name']}/{self._static_configuration['mqtt']['topic']['event']}",
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
        """Add a reading and calculate the battery level from the recent average.

        Brief current spikes make single voltage readings jump, so the level
        is worked out from the average of the last `battery.average_readings`
        readings. The load correction is linear, so averaging the voltage and
        current first gives the same result as averaging corrected voltages.
        """
        self._battery_readings.append((voltage, current))
        count = len(self._battery_readings)

        return self._calculate_battery_level(
            sum(reading[0] for reading in self._battery_readings) / count,
            sum(reading[1] for reading in self._battery_readings) / count,
        )

    def _calculate_battery_level(self, voltage: float, current: float = 0.0) -> int:
        """Calculate Battery Level.

        The battery voltage sags under load by roughly current x internal
        resistance, so that is added back to estimate the resting voltage.
        Charging current is negative, so the rise while charging is taken off.
        A resistance of 0 leaves the voltage as measured.

        The resting voltage is then turned into a level using `battery.curve`
        when it is configured, as a Li-ion battery's voltage isn't linear with
        its charge. Otherwise a straight line between the minimum and maximum
        voltage is used.
        """
        battery_configuration = self._static_configuration.get("battery", {})
        internal_resistance = float(
            battery_configuration.get(
                "internal_resistance",
                DEFAULT_BATTERY_INTERNAL_RESISTANCE,
            ),
        )
        resting_voltage = voltage + current / 1000 * internal_resistance / 1000

        curve = battery_configuration.get("curve")
        if curve:
            return round(self._interpolate_battery_curve(curve, resting_voltage))

        return self._calculate_linear_battery_level(resting_voltage)

    @staticmethod
    def _interpolate_battery_curve(curve: list[list[float]], voltage: float) -> float:
        """Interpolate the battery level between the points of the curve.

        The curve is checked at start up to have rising voltages, so it can be
        walked in order. Voltages outside it are clamped to its ends.
        """
        if voltage <= curve[0][0]:
            return curve[0][1]

        for lower, upper in pairwise(curve):
            lower_voltage, lower_level = lower
            upper_voltage, upper_level = upper
            if voltage <= upper_voltage:
                return lower_level + (voltage - lower_voltage) / (
                    upper_voltage - lower_voltage
                ) * (upper_level - lower_level)

        return curve[-1][1]

    def _calculate_linear_battery_level(self, voltage: float) -> int:
        """Calculate the battery level on a straight line between two voltages.

        Subtracting DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP from the ceiling
        prevents the level from reaching 100% while the battery is still under
        load (voltage sags slightly even when fully charged).  min/max clamp
        the result to [0, 100] so transient out-of-range readings are safe.

        If the configured minimum is not below the maximum the scale would be
        inverted and the level could never reach 0%, so low battery shutdown
        would never happen. In that case the default voltages are used instead.
        """
        voltage_minimum = self.data.battery_voltage_minimum
        voltage_maximum = self.data.battery_voltage_maximum
        if voltage_maximum - DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP <= voltage_minimum:
            self.logger.error(
                "Battery voltage minimum %fV is not below maximum %fV, "
                "using the default %fV to %fV instead",
                voltage_minimum,
                voltage_maximum,
                DEFAULT_BATTERY_VOLTAGE_MINIMUM,
                DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
            )
            voltage_minimum = DEFAULT_BATTERY_VOLTAGE_MINIMUM
            voltage_maximum = DEFAULT_BATTERY_VOLTAGE_MAXIMUM

        return int(
            max(
                min(
                    100,
                    (voltage - voltage_minimum)
                    / (
                        voltage_maximum
                        - DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP
                        - voltage_minimum
                    )
                    * 100,
                ),
                0,
            ),
        )

    def _calculate_battery_time_remaining(self) -> float | None:
        """Estimate the days left on battery before the low battery shutdown.

        The charge left above the shutdown level, taken from the battery
        capacity and the voltage based battery level, divided by the current
        being drawn. The battery level is not linear with charge and the
        current changes with load, so this is a rough guide only.

        Returns None (unknown in Home Assistant) when the capacity isn't set,
        or when there is external power so the battery isn't discharging.
        """
        if (
            self.data.battery_capacity <= 0
            or self.data.external_power
            or self.data.current <= 0
        ):
            return None

        usable_percentage = max(
            self.data.battery_level - self.data.battery_warning_threshold,
            0,
        )
        remaining_mah = self.data.battery_capacity * usable_percentage / 100

        return round(remaining_mah / self.data.current / HOURS_PER_DAY, 3)

    def _update_cpu_information(self) -> None:
        """Update CPU information, including temperature and throttling."""
        try:
            # Temperature
            self.data.cpu_temperature = read_cpu_temperature()

            # Throttled state
            self.data.cpu_stat_raw = read_cpu_stat()

            # Decode text
            self.data.cpu_stat_text = (
                decode_cpu_stat_text(self.data.cpu_stat_raw)
                if self.data.cpu_stat_raw is not None
                else "Error"
            )

        except Exception:
            self.logger.exception("Failed to read CPU Information")
            self.data.cpu_temperature = None
            self.data.cpu_stat_raw = None
            self.data.cpu_stat_text = None

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
        # Force a update of the dynamic configuration values
        self._update_dynamic_configuration()

        # Update CPU information before publishing info
        self._update_cpu_information()

        self.data.battery_time_remaining = self._calculate_battery_time_remaining()

        # Publish heartbeat to status endpoint
        MQTT.event.emit(
            event_name="publish",
            topic=f"{self._static_configuration['mqtt']['base_topic']}/{self._static_configuration['hostname']['name']}/{self._static_configuration['mqtt']['topic']['status']}",
            payload=f"{self._static_configuration['status']['online']}",
            qos=1,
            retain=True,
        )

        # Publish latest data to state endpoint
        MQTT.event.emit(
            event_name="publish",
            topic=f"{self._static_configuration['mqtt']['base_topic']}/{self._static_configuration['hostname']['name']}/{self._static_configuration['mqtt']['topic']['state']}",
            payload=json.dumps(
                {
                    f"{self._static_configuration['fields']['voltage']['name']}": round(
                        self.data.voltage,
                        3,
                    ),
                    # The INA219 reads the discharge current as positive. It is
                    # published the other way round, negative while the battery
                    # is discharging and positive while it is charging.
                    # Adding 0.0 turns -0.0 (a zero reading negated) into 0.0
                    f"{self._static_configuration['fields']['current']['name']}": round(
                        -self.data.current,
                        4,
                    )
                    + 0.0,
                    f"{self._static_configuration['fields']['power']['name']}": round(
                        self.data.power,
                        3,
                    ),
                    f"{self._static_configuration['fields']['battery_level']['name']}": self.data.battery_level,  # noqa: E501
                    f"{self._static_configuration['fields']['external_power']['name']}": (  # noqa: E501
                        self._static_configuration["fields"][  # noqa: E501
                            "external_power"
                        ].get(
                            "payload_on",
                            "ON",
                        )
                        if self.data.external_power
                        else self._static_configuration["fields"]["external_power"].get(
                            "payload_off",
                            "OFF",
                        )
                    ),
                    f"{self._static_configuration['fields']['charging']['name']}": (
                        self._static_configuration["fields"]["charging"].get(
                            "payload_on",
                            "ON",
                        )
                        if self.data.charging
                        else self._static_configuration["fields"]["charging"].get(
                            "payload_off",
                            "OFF",
                        )
                    ),
                    f"{self._static_configuration['fields']['cpu_temperature']['name']}": self.data.cpu_temperature,  # noqa: E501
                    f"{self._static_configuration['fields']['under_voltage']['name']}": self._cpu_stat_payload(  # noqa: E501
                        "under_voltage",
                        UNDER_VOLTAGE_MASK,
                    ),
                    f"{self._static_configuration['fields']['throttled']['name']}": self._cpu_stat_payload(  # noqa: E501
                        "throttled",
                        THROTTLED_MASK,
                    ),
                    f"{self._static_configuration['fields']['cpu_stat_text']['name']}": self.data.cpu_stat_text,  # noqa: E501
                    f"{self._static_configuration['fields']['battery_warning_threshold']['name']}": self.data.battery_warning_threshold,  # noqa: E501
                    f"{self._static_configuration['fields']['battery_voltage_minimum']['name']}": self.data.battery_voltage_minimum,  # noqa: E501
                    f"{self._static_configuration['fields']['battery_voltage_maximum']['name']}": self.data.battery_voltage_maximum,  # noqa: E501
                    f"{self._static_configuration['fields']['report_interval']['name']}": self.data.report_interval,  # noqa: E501
                    f"{self._static_configuration['fields']['battery_capacity']['name']}": self.data.battery_capacity,  # noqa: E501
                    f"{self._static_configuration['fields']['battery_time_remaining']['name']}": self.data.battery_time_remaining,  # noqa: E501
                },
            ),
            # Retained so Home Assistant gets the latest readings as soon as
            # it subscribes, after discovery or its own restart, instead of
            # waiting for the next report. The status topic's Last Will marks
            # them unavailable if this device drops off.
            retain=True,
        )

    def _cpu_stat_payload(self, field: str, mask: int) -> str | None:
        """Return a binary sensor payload for bits of the throttling bitmask.

        None (unknown in Home Assistant) when the bitmask couldn't be read.
        """
        if self.data.cpu_stat_raw is None:
            return None

        field_configuration = self._static_configuration["fields"][field]
        if self.data.cpu_stat_raw & mask:
            return str(field_configuration.get("payload_on", "ON"))
        return str(field_configuration.get("payload_off", "OFF"))

    def _update_dynamic_configuration(self) -> None:
        """Update Dynamic Configuration.

        This uses a event hook back to the Dynamic Configuration to update the file.
        The dynamic configuration is keyed by field key, not by the configurable
        field name used for MQTT topics and payloads.
        """
        # Update Battery Warning Threshold
        self.data.battery_warning_threshold = int(
            self._dynamic_configuration.data["battery_warning_threshold"],
        )

        # Update Battery Voltage Minimum
        self.data.battery_voltage_minimum = float(
            self._dynamic_configuration.data["battery_voltage_minimum"],
        )

        # Update Battery Voltage Maximum
        self.data.battery_voltage_maximum = float(
            self._dynamic_configuration.data["battery_voltage_maximum"],
        )

        # Update Report Interval
        self.data.report_interval = int(
            self._dynamic_configuration.data["report_interval"],
        )

        # Update Battery Capacity
        self.data.battery_capacity = int(
            self._dynamic_configuration.data["battery_capacity"],
        )

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
