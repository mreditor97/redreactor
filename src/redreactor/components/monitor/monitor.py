"""Monitor module."""

import json
import logging
import subprocess
import sys
from typing import Any

from ina219 import INA219, DeviceRangeError
from paho.mqtt.client import Client

from redreactor.components.mqtt import MQTT
from redreactor.configuration import DynamicConfiguration
from redreactor.const import (
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
    DEFAULT_BATTERY_VOLTAGE_MINIMUM,
    DEFAULT_BATTERY_WARNING_THRESHOLD,
    DEFAULT_REPORT_INTERVAL,
)
from redreactor.helpers.emitter import EventEmitter
from redreactor.helpers.repeater import RepeatTimer

from .data import MonitorData


class Monitor:
    """Monitor module.

    Used to monitor the state of the Red Reactor
    """

    logger = logging.getLogger("Red Reactor")

    event: EventEmitter = EventEmitter()

    _static_configuration: dict[str, Any]
    _dynamic_configuration: DynamicConfiguration

    # Adds default values into the Monitor Data dict
    data: MonitorData = MonitorData(
        voltage=0.0,
        current=0.0,
        battery_level=100,
        external_power=True,
        cpu_temperature=0.0,
        cpu_stat=0,
        battery_warning_threshold=DEFAULT_BATTERY_WARNING_THRESHOLD,
        battery_voltage_minimum=DEFAULT_BATTERY_VOLTAGE_MINIMUM,
        battery_voltage_maximum=DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
        report_interval=DEFAULT_REPORT_INTERVAL,
    )

    # Timers
    monitor_timer: RepeatTimer  # Runs Monitoring calculations
    report_timer: RepeatTimer  # Pushes updates to MQTT

    def __init__(
        self,
        static_configuration: Any,
        dynamic_configuration: DynamicConfiguration,
    ) -> None:
        """Initialise Monitor object."""
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
                busnum=1,
                log_level=logging.ERROR,
            )
            ina.configure(voltage_range=ina.RANGE_16V)
        except (OSError, ModuleNotFoundError):
            self.logger.exception("Unable to connect to the Red Reactor")

            # Exit the program
            sys.exit(0)

        # Configure the monitor timer, start's as soon as possible
        self.monitor_timer = RepeatTimer(
            float(self._static_configuration["ina"]["monitor_interval"]),
            self._monitor,
            ina=ina,
        )
        self.monitor_timer.start()

    def _monitor(self, ina: INA219) -> None:  # noqa: PLR0912
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
            except DeviceRangeError:
                # Assume no external power so the device will still shutdown on a low voltage reading # noqa: E501
                self.logger.exception("Battery current range error")
                self.data.external_power = False
                self.data.current = 6000

                MQTT.event.emit(
                    event_name="publish",
                    topic=f"{self._static_configuration['mqtt']['base_topic']}/{self._static_configuration['hostname']['name']}/{self._static_configuration['mqtt']['topic']['status']}",  # noqa: E501
                    payload=f"{self._static_configuration['status']['offline']}",
                )
            except ZeroDivisionError:
                self.logger.exception(
                    "Minimum Voltage %fV and Maximum Voltage %fV difference is equal to 0",  # noqa: E501
                    self.data.battery_voltage_minimum,
                    self.data.battery_voltage_maximum,
                )
            else:
                # Identify status change
                if self.data.current > 10:
                    # No External Power
                    if self.data.external_power:
                        # Power removed
                        self.data.external_power = False
                        self._update()
                elif self.data.current >= 0:
                    # Battery now Full
                    self.data.external_power = True
                else:
                    # Charging
                    if not self.data.external_power:  # noqa: PLR5501
                        # Power restored
                        self.data.external_power = True
                        self._update()

        if (
            self.data.battery_level <= float(self.data.battery_warning_threshold)
            and not self.data.external_power
        ):
            # Force immediate publish update at warning level
            self._update()

        if self.data.battery_level == 0.0 and not self.data.external_power:
            shutdown = True

        if self.data.voltage > self.data.battery_voltage_maximum + 0.05:
            self.data.external_power = True
            # Force immediate publish update at warning level
            self._update()

        # Shutdown system
        if shutdown:
            self.logger.warning(
                "Forcing system shutdown, going offline with %fV",
                round(self.data.voltage, 2),
            )

            # Emit the shutdown event
            self.event.emit("shutdown")

    def _calculate_battery_level(self, voltage: float) -> int:
        """Calculate Battery Level."""
        return int(
            max(
                min(
                    100,
                    (voltage - self.data.battery_voltage_minimum)
                    / (
                        self.data.battery_voltage_maximum
                        - 0.05
                        - self.data.battery_voltage_minimum
                    )
                    * 100,
                ),
                0,
            ),
        )

    def _update(self) -> None:
        """Pushes the latest data to Monitor endpoint."""
        # Force a update of the dynamic configuration values
        self._update_dynamic_configuration()

        # Read data from Kernel endpoints
        try:
            cpu_temperature = subprocess.Popen(
                ["cat", "/sys/class/thermal/thermal_zone0/temp"],  # noqa: S603, S607
                stdout=subprocess.PIPE,
            )
            result_cpu_temperature = cpu_temperature.communicate()
            self.data.cpu_temperature = round(
                float((result_cpu_temperature[0]).decode()) * 0.001,
                2,
            )

            cpu_stat = subprocess.Popen(
                [  # noqa: S603, S607
                    "cat",
                    "/sys/devices/platform/soc/soc:firmware/get_throttled",
                ],
                stdout=subprocess.PIPE,
            )
            result_cpu_stat = cpu_stat.communicate()
            self.data.cpu_stat = int(result_cpu_stat[0].decode())
        except (OSError, IndexError, ValueError):
            # Failed to extract info
            self.logger.exception("Failed to read CPU Information")
            self.data.cpu_stat = None
            self.data.cpu_temperature = None

        # Publish heartbeat to status endpoint
        MQTT.event.emit(
            event_name="publish",
            topic=f"{self._static_configuration['mqtt']['base_topic']}/{self._static_configuration['hostname']['name']}/{self._static_configuration['mqtt']['topic']['status']}",
            payload=f"{self._static_configuration['status']['online']}",
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
                    f"{self._static_configuration['fields']['battery_level']['name']}": self.data.battery_level,  # noqa: E501
                    f"{self._static_configuration['fields']['external_power']['name']}": self._static_configuration[  # noqa: E501
                        "fields"
                    ][
                        "external_power"
                    ].get(
                        "payload_on",
                        "ON",
                    )
                    if self.data.external_power
                    else self._static_configuration["fields"]["external_power"].get(
                        "payload_off",
                        "OFF",
                    ),
                    f"{self._static_configuration['fields']['cpu_temperature']['name']}": self.data.cpu_temperature,  # noqa: E501
                    f"{self._static_configuration['fields']['cpu_stat']['name']}": self.data.cpu_stat,  # noqa: E501
                    f"{self._static_configuration['fields']['battery_warning_threshold']['name']}": self.data.battery_warning_threshold,  # noqa: E501
                    f"{self._static_configuration['fields']['battery_voltage_minimum']['name']}": self.data.battery_voltage_minimum,  # noqa: E501
                    f"{self._static_configuration['fields']['battery_voltage_maximum']['name']}": self.data.battery_voltage_maximum,  # noqa: E501
                    f"{self._static_configuration['fields']['report_interval']['name']}": self.data.report_interval,  # noqa: E501
                },
            ),
        )

    def _update_dynamic_configuration(self) -> None:
        """Update Dynamic Configuration.

        This uses a event hook back to the Dynamic Configuration to update the file.
        """
        # Update Battery Warning Threshold
        self.data.battery_warning_threshold = int(
            self._dynamic_configuration.data[
                self._static_configuration["fields"]["battery_warning_threshold"][
                    "name"
                ]
            ],
        )

        # Update Battery Voltage Minimum
        self.data.battery_voltage_minimum = float(
            self._dynamic_configuration.data[
                self._static_configuration["fields"]["battery_voltage_minimum"]["name"]
            ],
        )

        # Update Battery Voltage Maximum
        self.data.battery_voltage_maximum = float(
            self._dynamic_configuration.data[
                self._static_configuration["fields"]["battery_voltage_maximum"]["name"]
            ],
        )

        # Update Report Interval
        self.data.report_interval = int(
            self._dynamic_configuration.data[
                self._static_configuration["fields"]["report_interval"]["name"]
            ],
        )

        if self.report_timer:
            # Update Monitor timer interval
            self.report_timer.interval = self.data.report_interval

    def _mqtt_on_connect(  # noqa: PLR0913
        self,
        client: Client,  # noqa: ARG002
        userdata: Any,  # noqa: ARG002
        flags: Any,  # noqa: ARG002
        rc: Any,  # noqa: ARG002
        reasoncode: Any = None,  # noqa: ARG002
    ) -> None:
        """On MQTT Connect.

        Start the reporting timer.
        """
        self.report_timer.start()
