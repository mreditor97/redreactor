"""Monitor module."""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import TYPE_CHECKING, Any

from ina219 import INA219, DeviceRangeError

from redreactor.components.monitor.data import MonitorData
from redreactor.components.mqtt import MQTT
from redreactor.const import (
    DEFAULT_BATTERY_VOLTAGE_HEADROOM,
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP,
    DEFAULT_BATTERY_VOLTAGE_MINIMUM,
    DEFAULT_BATTERY_WARNING_THRESHOLD,
    DEFAULT_REPORT_INTERVAL,
    DEFAULT_SHUTDOWN_CONSECUTIVE_READINGS,
)
from redreactor.helpers.cpu_utils import (
    decode_cpu_stat_text,
    read_cpu_stat,
    read_cpu_temperature,
)
from redreactor.helpers.emitter import EventEmitter
from redreactor.helpers.repeater import RepeatTimer

if TYPE_CHECKING:
    from paho.mqtt.client import Client

    from redreactor.configuration import DynamicConfiguration


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
            "current": round(current, 4),
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

    # time.monotonic() when external power was lost, None while it is present
    _on_battery_since: float | None = None

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

        # Register Dynamic Configuration update listener
        self._dynamic_configuration.event.on(event_name="write", function=self._update)

        # Register MQTT on connect listener
        MQTT.event.on(event_name="on_connect", function=self._mqtt_on_connect)

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
                self.data.battery_level = self._calculate_battery_level(
                    self.data.voltage,
                )
                self.data.current = ina.current()
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
                self.data.external_power = False
                self.data.charging = False
                self.data.current = (
                    float(self._static_configuration["ina"]["max_expected_amps"]) * 1000
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
                    if self.data.external_power:
                        # Transition: power just removed
                        self.data.external_power = False
                        self._update()
                elif self.data.current >= 0:
                    if not self.data.external_power:
                        # Transition: power restored, battery now floating
                        self.data.external_power = True
                        self._update()
                elif not self.data.external_power:
                    # Transition: power restored, battery actively charging
                    self.data.external_power = True
                    self._update()

        # Voltage above the nominal maximum indicates external power is present
        # (e.g. charger connected but INA219 current read was noisy/stale).
        # Checked before the warning and shutdown decisions so they use it.
        if (
            self.data.voltage
            > self.data.battery_voltage_maximum + DEFAULT_BATTERY_VOLTAGE_HEADROOM
            and not self.data.external_power
        ):
            # Transition: power detected from voltage, publish it straight away
            self.data.external_power = True
            self._update()

        if ina and not self._start_up_checked:
            self._start_up_checked = True
            self._check_start_up_charge()

        if (
            self.data.battery_level <= float(self.data.battery_warning_threshold)
            and not self.data.external_power
        ):
            # Publish immediately so Home Assistant reflects the warning without
            # waiting for the next scheduled report_interval tick.
            self._update()

            self._empty_readings += 1
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

        if self._battery_runtime_exceeded():
            shutdown = True

        # Shutdown system
        if shutdown:
            self.logger.warning(
                "Forcing system shutdown, going offline with %fV",
                round(self.data.voltage, 2),
            )

            # Emit the shutdown event
            self.event.emit("shutdown")

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

    def _battery_runtime_exceeded(self) -> bool:
        """Check whether the device has been on battery for too long.

        Tracks how long external power has been missing, and returns True once
        that is longer than the battery runtime limit. A limit of 0 disables it.
        """
        if self.data.external_power:
            self._on_battery_since = None
            return False

        now = time.monotonic()
        if self._on_battery_since is None:
            self._on_battery_since = now

        if self.data.battery_runtime_limit <= 0:
            return False

        on_battery_minutes = (now - self._on_battery_since) / 60
        if on_battery_minutes < self.data.battery_runtime_limit:
            return False

        self.logger.warning(
            "On battery for %.1f minutes, over the %i minute runtime limit",
            on_battery_minutes,
            self.data.battery_runtime_limit,
        )
        return True

    def _calculate_battery_level(self, voltage: float) -> int:
        """Calculate Battery Level.

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

    def _update(self) -> None:
        """Pushes the latest data to Monitor endpoint."""
        # Force a update of the dynamic configuration values
        self._update_dynamic_configuration()

        # Update CPU information before publishing info
        self._update_cpu_information()

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
                    f"{self._static_configuration['fields']['current']['name']}": round(
                        self.data.current,
                        4,
                    ),
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
                    f"{self._static_configuration['fields']['cpu_stat_raw']['name']}": self.data.cpu_stat_raw,  # noqa: E501
                    f"{self._static_configuration['fields']['cpu_stat_text']['name']}": self.data.cpu_stat_text,  # noqa: E501
                    f"{self._static_configuration['fields']['battery_warning_threshold']['name']}": self.data.battery_warning_threshold,  # noqa: E501
                    f"{self._static_configuration['fields']['battery_voltage_minimum']['name']}": self.data.battery_voltage_minimum,  # noqa: E501
                    f"{self._static_configuration['fields']['battery_voltage_maximum']['name']}": self.data.battery_voltage_maximum,  # noqa: E501
                    f"{self._static_configuration['fields']['report_interval']['name']}": self.data.report_interval,  # noqa: E501
                    f"{self._static_configuration['fields']['battery_runtime_limit']['name']}": self.data.battery_runtime_limit,  # noqa: E501
                },
            ),
        )

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

        # Update Battery Runtime Limit
        self.data.battery_runtime_limit = int(
            self._dynamic_configuration.data["battery_runtime_limit"],
        )

        if self.report_timer:
            # Update Monitor timer interval
            self.report_timer.interval = self.data.report_interval

    def _mqtt_on_connect(
        self,
        _client: Client,
        _userdata: Any,
        _flags: Any,
        _reason_code: Any,
        _properties: Any = None,
    ) -> None:
        """On MQTT Connect.

        Start the reporting timer.
        """
        self.report_timer.start()
