import json
import logging
import subprocess

from typing import Any
from paho.mqtt.client import Client
from ina219 import INA219, DeviceRangeError

from events.emitter import EventEmitter
from configuration import DynamicConfiguration
from events.repeater import RepeatTimer
from monitor.data import MonitorData
from mqtt.mqtt import MQTT
from const import (
    DEFAULT_REPORT_INTERVAL,
    DEFAULT_BATTERY_WARNING_THRESHOLD,
    DEFAULT_BATTERY_VOLTAGE_MINIMUM,
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
)


class Monitor:
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
        cpu_stat=0.0,
        battery_warning_threshold=DEFAULT_BATTERY_WARNING_THRESHOLD,
        battery_voltage_minimum=DEFAULT_BATTERY_VOLTAGE_MINIMUM,
        battery_voltage_maximum=DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
        report_interval=DEFAULT_REPORT_INTERVAL,
    )

    # Timers
    monitor_timer: RepeatTimer = None  # Runs Monitoring calculations
    report_timer: RepeatTimer = None  # Pushes updates to MQTT

    def __init__(
        self, static_configuration, dynamic_configuration: DynamicConfiguration
    ):
        self._static_configuration = static_configuration
        self._dynamic_configuration = dynamic_configuration

        # Register Dynamic Configuration update listener
        self._dynamic_configuration.event.on(event_name="write", function=self._update)

        # Register MQTT on connect listener
        MQTT.event.on(event_name="on_connect", function=self._mqtt_on_connect)

        self.logger.info("Initiating battery monitor")

        # Update Dynamic Configuration values to there latest values
        self._update_dynamic_configuration()

        # Setup the INA219
        ina: INA219 = None
        try:
            ina = INA219(
                shunt_ohms=static_configuration["ina"]["shunt_ohms"],
                max_expected_amps=static_configuration["ina"]["max_expected_amps"],
                address=static_configuration["ina"]["address"],
                busnum=1,
                log_level=logging.ERROR,
            )
            ina.configure(voltage_range=ina.RANGE_16V)
        except (OSError, ModuleNotFoundError) as error:
            self.logger.error(f"Unable to connect to the Red Reactor {error}")

            # Exit the program
            exit(0)

        # Configure the monitor timer, start's as soon as possible
        self.monitor_timer = RepeatTimer(
            float(self._static_configuration["ina"]["monitor_interval"]),
            self._monitor,
            ina=ina,
        )
        self.monitor_timer.start()

        # Configure the report timer, get's started on MQTT connect
        self.report_timer = RepeatTimer(
            self.data.report_interval,
            self._update,
        )

    def _monitor(self, ina: INA219):
        self.logger.debug("Monitoring thread has been started")

        # Update the Dynamic Configuration to ensure the calculations will be based correctly off the changable values
        self._update_dynamic_configuration()

        shutdown: bool = False

        if ina:
            try:
                self.data.voltage = ina.voltage()
                self.data.battery_level = self._calculate_battery_level(
                    self.data.voltage
                )
                self.data.current = ina.current()
            except DeviceRangeError as error:
                # Assume no external power so the device will still shutdown on a low voltage reading
                self.logger.error(f"Battery current range error: {error}")
                self.data.external_power = False
                self.data.current = 6000

                MQTT.event.emit(
                    event_name="publish",
                    topic=f"{self._static_configuration['mqtt']['base_topic']}/{self._static_configuration['hostname']['name']}/{self._static_configuration['mqtt']['topic']['status']}",
                    payload=f"{self._static_configuration['status']['offline']}",
                )
            except ZeroDivisionError:
                self.logger.error(
                    f"Minimum Voltage {self.data.battery_voltage_minimum}V and Maximum Voltage {self.data.battery_voltage_maximum}V difference is equal to 0"
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
                    if not self.data.external_power:
                        # Power restored
                        self.data.external_power = True
                        self._update()

        if (
            self.data.battery_level <= self.data.battery_warning_threshold
            and not self.data.external_power
        ):
            # Force immediate publish update at warning level
            self._update()

        if self.data.battery_level == 0 and not self.data.external_power:
            shutdown = True

        if self.data.voltage > self.data.battery_voltage_maximum + 0.05:
            self.data.external_power = True
            # Force immediate publish update at warning level
            self._update()

        # Shutdown system
        if shutdown:
            self.logger.warning(
                "Forcing system shutdown, going offline with {:.2f}V".format(
                    self.data.voltage
                )
            )

            # Emit the shutdown event
            self.event.emit("shutdown")

    def _calculate_battery_level(self, voltage: float):
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
            )
        )

    def _update(self):
        """Pushes the latest data to Monitor endpoint"""

        # Force a update of the dynamic configuration values
        self._update_dynamic_configuration()

        # Read data from Kernel endpoints
        try:
            cpu_temperature = subprocess.Popen(
                ["cat", "/sys/class/thermal/thermal_zone0/temp"], stdout=subprocess.PIPE
            )
            cpu_temperature = cpu_temperature.communicate()
            self.data.cpu_temperature = float(cpu_temperature[0].decode()) * 0.001

            cpu_stat = subprocess.Popen(
                ["cat", "/sys/devices/platform/soc/soc:firmware/get_throttled"],
                stdout=subprocess.PIPE,
            )
            cpu_stat = cpu_stat.communicate()
            self.data.cpu_stat = int(cpu_stat[0].decode())
        except (OSError, IndexError, ValueError):
            # Failed to extract info
            self.logger.error("Failed to read CPU Information")
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
                dict(
                    {
                        f"{self._static_configuration['fields']['voltage']['name']}": round(
                            self.data.voltage, 3
                        ),
                        f"{self._static_configuration['fields']['current']['name']}": round(
                            self.data.current, 4
                        ),
                        f"{self._static_configuration['fields']['battery_level']['name']}": self.data.battery_level,
                        f"{self._static_configuration['fields']['external_power']['name']}": f"{self._static_configuration['fields']['external_power'].get('payload_on', 'ON') if self.data.external_power else self._static_configuration['fields']['external_power'].get('payload_off', 'OFF')}",
                        f"{self._static_configuration['fields']['cpu_temperature']['name']}": round(
                            self.data.cpu_temperature, 3
                        ),
                        f"{self._static_configuration['fields']['cpu_stat']['name']}": self.data.cpu_stat,
                        f"{self._static_configuration['fields']['battery_warning_threshold']['name']}": self.data.battery_warning_threshold,
                        f"{self._static_configuration['fields']['battery_voltage_minimum']['name']}": self.data.battery_voltage_minimum,
                        f"{self._static_configuration['fields']['battery_voltage_maximum']['name']}": self.data.battery_voltage_maximum,
                        f"{self._static_configuration['fields']['report_interval']['name']}": self.data.report_interval,
                    }
                )
            ),
        )

    def _update_dynamic_configuration(self):
        """Updates Dynamic Configuration values to there latest values"""

        # Update Battery Warning Threshold
        self.data.battery_warning_threshold = float(
            self._dynamic_configuration.data[
                self._static_configuration["fields"]["battery_warning_threshold"][
                    "name"
                ]
            ]
        )

        # Update Battery Voltage Minimum
        self.data.battery_voltage_minimum = float(
            self._dynamic_configuration.data[
                self._static_configuration["fields"]["battery_voltage_minimum"]["name"]
            ]
        )

        # Update Battery Voltage Maximum
        self.data.battery_voltage_maximum = float(
            self._dynamic_configuration.data[
                self._static_configuration["fields"]["battery_voltage_maximum"]["name"]
            ]
        )

        # Update Report Interval
        self.data.report_interval = int(
            self._dynamic_configuration.data[
                self._static_configuration["fields"]["report_interval"]["name"]
            ]
        )

        if self.report_timer:
            # Update Monitor timer interval
            self.report_timer.interval = self.data.report_interval

    def _mqtt_on_connect(self, client: Client, userdata, flags, rc, reasonCode):
        self.report_timer.start()
