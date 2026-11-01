"""Configuration module.

Contains the ability to read the static and dynamic configuration files.
"""

from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
from typing import Any

import yaml

from redreactor.const import (
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP,
    DEFAULT_BATTERY_VOLTAGE_MINIMUM,
    DEFAULT_BATTERY_WARNING_THRESHOLD,
    DEFAULT_INA_I2C_ADDRESS,
    DEFAULT_INA_MAX_EXPECTED_AMPS,
    DEFAULT_INA_MONITOR_INTERVAL,
    DEFAULT_INA_SHUNT_OHMS,
    DEFAULT_REPORT_INTERVAL,
)
from redreactor.helpers.emitter import EventEmitter
from redreactor.helpers.utils import dict_merge

logger = logging.getLogger("Red Reactor")


class DynamicConfiguration:
    """Dynamic Configuration object."""

    data: dict[str, Any]

    event: EventEmitter

    _dynamic_file: str

    def __init__(self, dynamic_file: str) -> None:
        """Initialise the Dynamic Configuration object."""
        self._dynamic_file = dynamic_file
        self.event = EventEmitter()

        self.data = self._load()

        # Self-register so any component can persist a config change simply by
        # emitting "write" on this event, without needing a direct reference.
        self.event.on(event_name="write", function=self.write)

    def _load(self) -> Any:
        """Load dynamic configuration file."""
        dynamic_file_defaults = {
            "report_interval": DEFAULT_REPORT_INTERVAL,
            "battery_warning_threshold": DEFAULT_BATTERY_WARNING_THRESHOLD,
            "battery_voltage_minimum": DEFAULT_BATTERY_VOLTAGE_MINIMUM,
            "battery_voltage_maximum": DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
        }

        dynamic_path = Path(self._dynamic_file)
        if not dynamic_path.exists():
            with dynamic_path.open("w") as file:
                json.dump(dynamic_file_defaults, file)

        with dynamic_path.open() as file:
            dynamic_file_override = json.load(file)

        # Simple dict unpack is fine here — the dynamic config is flat (no
        # nested dicts), so override values win without recursive merging.
        data = {**dynamic_file_defaults, **dynamic_file_override}

        # Older versions stored received values without checking them, so a
        # non-numeric value would stop the service from ever starting again.
        for key, default in dynamic_file_defaults.items():
            value = data[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
            ):
                logger.warning(
                    "Invalid %s value %r in %s, using the default %s",
                    key,
                    value,
                    self._dynamic_file,
                    default,
                )
                data[key] = default

        # An inverted voltage range would disable low battery shutdown
        if (
            data["battery_voltage_minimum"]
            >= data["battery_voltage_maximum"] - DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP
        ):
            logger.warning(
                "Battery voltage minimum %s is not below maximum %s in %s, "
                "using the defaults",
                data["battery_voltage_minimum"],
                data["battery_voltage_maximum"],
                self._dynamic_file,
            )
            data["battery_voltage_minimum"] = DEFAULT_BATTERY_VOLTAGE_MINIMUM
            data["battery_voltage_maximum"] = DEFAULT_BATTERY_VOLTAGE_MAXIMUM

        return data

    def write(self) -> None:
        """Write dynamic configuration file.

        Written to a temporary file and then renamed over the original, so a
        power cut part way through can't leave a truncated file behind.
        """
        dynamic_path = Path(self._dynamic_file)
        temporary_path = dynamic_path.with_name(f"{dynamic_path.name}.tmp")
        with temporary_path.open("w") as file:
            json.dump(self.data, file)
            file.flush()
            os.fsync(file.fileno())
        temporary_path.replace(dynamic_path)


class LinkedConfiguration:
    """Linked Configuration.

    A connection between both Dynamic and Static configurations.
    """

    static: dict[str, Any]
    dynamic: DynamicConfiguration

    _static_file: str
    _dynamic_file: str

    def __init__(self, static_file: str, dynamic_file: str) -> None:
        """Initialise Linked Configuration object."""
        self._static_file = static_file
        self._dynamic_file = dynamic_file

        self.static = self._load()
        self.dynamic = DynamicConfiguration(self._dynamic_file)

    def _load(self) -> dict[str, Any]:
        """Load static configuration file, and override defaults."""
        with Path(self._static_file).open() as static_file:
            static_file_override = yaml.safe_load(static_file)

        static_file_defaults: dict[str, Any] = {
            "mqtt": {
                "broker": "127.0.0.1",
                "port": 1883,
                "user": "test",
                "password": "test",
                "base_topic": "redreactor",
                "version": 3,
                "transport": "tcp",
                "timeout": 120,
                "topic": {
                    "state": "state",
                    "status": "status",
                    "set": "set",
                },
                "exit_on_fail": True,
            },
            "hostname": {"name": "redreactor", "pretty": "Red Reactor"},
            "homeassistant": {
                "discovery": True,
                "topic": "homeassistant",
                "discovery_interval": 120,
                "expire_after": 120,
            },
            "status": {
                "online": "online",
                "offline": "offline",
            },
            "fields": {
                "voltage": {
                    "name": "voltage",
                    "pretty": "Voltage",
                    "type": "sensor",
                    "unit": "V",
                    "device_class": "voltage",
                    "suggested_display_precision": 2,
                },
                "current": {
                    "name": "current",
                    "pretty": "Current",
                    "type": "sensor",
                    "unit": "mA",
                    "device_class": "current",
                    "suggested_display_precision": 2,
                },
                "battery_level": {
                    "name": "battery_level",
                    "pretty": "Battery level",
                    "type": "sensor",
                    "unit": "%",
                    "device_class": "battery",
                },
                "external_power": {
                    "name": "external_power",
                    "pretty": "External power",
                    "type": "binary_sensor",
                    "device_class": "plug",
                    "entity_category": "diagnostic",
                },
                "cpu_temperature": {
                    "name": "cpu_temperature",
                    "pretty": "CPU temperature",
                    "type": "sensor",
                    "unit": "°C",
                    "device_class": "temperature",
                    "entity_category": "diagnostic",
                    "suggested_display_precision": 2,
                },
                "cpu_stat_raw": {
                    "name": "cpu_stat_raw",
                    "pretty": "CPU stat raw",
                    "type": "sensor",
                    "entity_category": "diagnostic",
                    "enabled_by_default": False,
                },
                "cpu_stat_text": {
                    "name": "cpu_stat",
                    "pretty": "CPU stat",
                    "type": "sensor",
                    "entity_category": "diagnostic",
                    "state_class": None,
                },
                "battery_warning_threshold": {
                    "name": "battery_warning_threshold",
                    "pretty": "Battery warning",
                    "type": "number",
                    "unit": "%",
                    "device_class": "battery",
                    "entity_category": "diagnostic",
                    "min": 0,
                    "max": 100,
                    "mode": "box",
                    "step": 1,
                },
                "battery_voltage_minimum": {
                    "name": "battery_voltage_minimum",
                    "pretty": "Battery voltage minimum",
                    "type": "number",
                    "unit": "V",
                    "device_class": "voltage",
                    "entity_category": "diagnostic",
                    "min": 2.5,
                    "max": 4.5,
                    "mode": "box",
                    "step": 0.1,
                },
                "battery_voltage_maximum": {
                    "name": "battery_voltage_maximum",
                    "pretty": "Battery voltage maximum",
                    "type": "number",
                    "unit": "V",
                    "device_class": "voltage",
                    "entity_category": "diagnostic",
                    "min": 2.5,
                    "max": 4.5,
                    "mode": "box",
                    "step": 0.1,
                },
                "report_interval": {
                    "name": "report_interval",
                    "pretty": "Report interval",
                    "type": "number",
                    "unit": "s",
                    "entity_category": "diagnostic",
                    "min": 5,
                    "max": 300,
                    "mode": "box",
                    "step": 5,
                },
                "restart": {
                    "name": "restart",
                    "pretty": "Restart",
                    "type": "button",
                    "entity_category": "diagnostic",
                },
                "shutdown": {
                    "name": "shutdown",
                    "pretty": "Shutdown",
                    "type": "button",
                    "entity_category": "diagnostic",
                },
            },
            "ina": {
                "address": DEFAULT_INA_I2C_ADDRESS,
                "shunt_ohms": DEFAULT_INA_SHUNT_OHMS,
                "max_expected_amps": DEFAULT_INA_MAX_EXPECTED_AMPS,
                "monitor_interval": DEFAULT_INA_MONITOR_INTERVAL,
            },
            "system": {
                "shutdown": "sudo shutdown 0 -h",
                "restart": "sudo shutdown 0 -r",
            },
            "logging": {
                "console": "INFO",
                "file": "WARNING",
            },
        }

        # Overwritten any different values with the ones that came from the static file
        dict_merge(static_file_defaults, static_file_override)

        # MQTT brokers disconnect a client when another connects with the same
        # ID, so default to one that is unique per configured hostname
        static_file_defaults["mqtt"].setdefault(
            "client_id",
            f"redreactor-{static_file_defaults['hostname']['name']}",
        )
        return static_file_defaults
