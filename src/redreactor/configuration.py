"""Configuration module.

Contains the ability to read the static and dynamic configuration files.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
from pathlib import Path
from typing import Any

import yaml

from redreactor.const import (
    DEFAULT_BATTERY_RUNTIME_LIMIT,
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP,
    DEFAULT_BATTERY_VOLTAGE_MINIMUM,
    DEFAULT_BATTERY_WARNING_THRESHOLD,
    DEFAULT_INA_I2C_ADDRESS,
    DEFAULT_INA_I2C_BUS,
    DEFAULT_INA_MAX_EXPECTED_AMPS,
    DEFAULT_INA_MONITOR_INTERVAL,
    DEFAULT_INA_SHUNT_OHMS,
    DEFAULT_REPORT_INTERVAL,
)
from redreactor.helpers.emitter import EventEmitter
from redreactor.helpers.utils import dict_merge

logger = logging.getLogger("Red Reactor")

# Valid 7-bit I2C addresses, 0x00-0x02 and 0x78-0x7F are reserved
I2C_ADDRESS_MINIMUM = 0x03
I2C_ADDRESS_MAXIMUM = 0x77
PORT_MAXIMUM = 65535


class ConfigurationError(ValueError):
    """Raised when the static configuration file contains invalid values."""


def _is_number(value: Any) -> bool:
    """Check for a finite int or float, bool is a subclass of int so is excluded."""
    return (
        not isinstance(value, bool)
        and isinstance(value, int | float)
        and math.isfinite(value)
    )


def _convert_quoted_values(configuration: dict[str, Any]) -> None:
    """Convert quoted numbers and booleans in place.

    Quoted values ("1883", "true") worked in earlier versions, so they are
    converted rather than refused at start.
    """
    for section, key in (
        ("mqtt", "port"),
        ("mqtt", "version"),
        ("mqtt", "timeout"),
        ("homeassistant", "discovery_interval"),
        ("homeassistant", "expire_after"),
        ("ina", "monitor_interval"),
        ("ina", "shunt_ohms"),
        ("ina", "max_expected_amps"),
        ("ina", "bus"),
    ):
        value = configuration[section][key]
        if isinstance(value, str):
            try:
                configuration[section][key] = int(value)
            except ValueError:
                with contextlib.suppress(ValueError):
                    configuration[section][key] = float(value)
    for section, key in (("mqtt", "exit_on_fail"), ("homeassistant", "discovery")):
        value = configuration[section][key]
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            configuration[section][key] = value.lower() == "true"
    tls = configuration["mqtt"].get("tls")
    if isinstance(tls, dict):
        for key in ("enabled", "insecure"):
            value = tls.get(key)
            if isinstance(value, str) and value.lower() in {"true", "false"}:
                tls[key] = value.lower() == "true"


def _validate_static(configuration: dict[str, Any]) -> list[str]:
    """Check the types and ranges of the merged static configuration.

    Returns a list of problems, empty when the configuration is valid. Values
    are checked up front so a typo fails at start with a clear message, rather
    than as a crash on a timer thread or a silently wrong setting later.
    """
    sections = (
        "mqtt",
        "hostname",
        "homeassistant",
        "status",
        "fields",
        "ina",
        "system",
        "logging",
    )
    errors = [
        f"`{section}` must be a mapping, got {configuration.get(section)!r}"
        for section in sections
        if not isinstance(configuration.get(section), dict)
    ]
    if not errors and not isinstance(configuration["mqtt"].get("topic"), dict):
        errors.append("`mqtt.topic` must be a mapping")
    if not errors and not isinstance(configuration["mqtt"].get("tls"), dict):
        errors.append(
            f"`mqtt.tls` must be a mapping, got {configuration['mqtt'].get('tls')!r}",
        )
    if errors:
        # The remaining checks index into these sections
        return errors

    def check(path: str, valid: bool, requirement: str) -> None:  # noqa: FBT001
        if not valid:
            section, _, key = path.rpartition(".")
            value = configuration
            for part in section.split("."):
                value = value[part]
            errors.append(f"`{path}` {requirement}, got {value[key]!r}")

    _convert_quoted_values(configuration)

    mqtt = configuration["mqtt"]
    homeassistant = configuration["homeassistant"]
    ina = configuration["ina"]

    # Booleans, bool() of any other text is True so it would be misread
    check(
        "mqtt.exit_on_fail",
        isinstance(mqtt["exit_on_fail"], bool),
        "must be true or false",
    )
    check(
        "homeassistant.discovery",
        isinstance(homeassistant["discovery"], bool),
        "must be true or false",
    )

    # Whole numbers
    check(
        "mqtt.port",
        _is_number(mqtt["port"])
        and float(mqtt["port"]).is_integer()
        and 1 <= mqtt["port"] <= PORT_MAXIMUM,
        f"must be a whole number from 1 to {PORT_MAXIMUM}",
    )
    check("mqtt.version", mqtt["version"] in {3, 5}, "must be 3 or 5")
    check(
        "mqtt.timeout",
        _is_number(mqtt["timeout"]) and mqtt["timeout"] >= 0,
        "must be a number of seconds, 0 or more",
    )
    check(
        "ina.address",
        not isinstance(ina["address"], bool)
        and isinstance(ina["address"], int)
        and I2C_ADDRESS_MINIMUM <= ina["address"] <= I2C_ADDRESS_MAXIMUM,
        f"must be an I2C address from {I2C_ADDRESS_MINIMUM:#04x} "
        f"to {I2C_ADDRESS_MAXIMUM:#04x}",
    )

    check(
        "ina.bus",
        not isinstance(ina["bus"], bool)
        and isinstance(ina["bus"], int)
        and ina["bus"] >= 0,
        "must be an I2C bus number, 0 or more",
    )

    errors.extend(_validate_tls(mqtt["tls"]))

    # Positive numbers, a zero interval would spin a timer thread
    for path, value in (
        ("homeassistant.discovery_interval", homeassistant["discovery_interval"]),
        ("ina.monitor_interval", ina["monitor_interval"]),
        ("ina.shunt_ohms", ina["shunt_ohms"]),
        ("ina.max_expected_amps", ina["max_expected_amps"]),
    ):
        check(path, _is_number(value) and value > 0, "must be a number above 0")
    check(
        "homeassistant.expire_after",
        _is_number(homeassistant["expire_after"])
        and homeassistant["expire_after"] >= 0,
        "must be a number of seconds, 0 or more",
    )

    # MQTT topic levels, wildcards are not allowed in a published topic and a
    # `/` in a single level would shift every topic the commands are matched on
    for path, value, allow_slash in (
        ("mqtt.base_topic", mqtt["base_topic"], True),
        ("homeassistant.topic", homeassistant["topic"], True),
        ("hostname.name", configuration["hostname"]["name"], False),
        ("mqtt.topic.state", mqtt["topic"]["state"], False),
        ("mqtt.topic.status", mqtt["topic"]["status"], False),
        ("mqtt.topic.set", mqtt["topic"]["set"], False),
    ):
        forbidden = "+#" if allow_slash else "+#/"
        check(
            path,
            isinstance(value, str)
            and value != ""
            and not any(character in value for character in forbidden),
            f"must be text without {' or '.join(forbidden)}",
        )

    for path, value in (
        ("system.shutdown", configuration["system"]["shutdown"]),
        ("system.restart", configuration["system"]["restart"]),
    ):
        check(path, isinstance(value, str) and value.strip() != "", "must be a command")

    return errors


def _validate_tls(tls: dict[str, Any]) -> list[str]:
    """Check the MQTT TLS options.

    The certificate paths themselves are checked by paho when the connection is
    set up, which stops the service if a file can't be read.
    """
    errors = [
        f"`mqtt.tls.{key}` must be true or false, got {tls[key]!r}"
        for key in ("enabled", "insecure")
        if not isinstance(tls[key], bool)
    ]
    errors.extend(
        f"`mqtt.tls.{key}` must be a file path, got {tls[key]!r}"
        for key in ("ca_certs", "certfile", "keyfile")
        if tls[key] is not None and not isinstance(tls[key], str)
    )
    return errors


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
            "battery_runtime_limit": DEFAULT_BATTERY_RUNTIME_LIMIT,
        }

        dynamic_path = Path(self._dynamic_file)
        if not dynamic_path.exists():
            with dynamic_path.open("w") as file:
                json.dump(dynamic_file_defaults, file)

        try:
            with dynamic_path.open() as file:
                dynamic_file_override = json.load(file)
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning(
                "Unable to read %s, using the default settings",
                self._dynamic_file,
            )
            dynamic_file_override = {}

        if not isinstance(dynamic_file_override, dict):
            logger.warning(
                "%s does not contain a JSON object, using the default settings",
                self._dynamic_file,
            )
            dynamic_file_override = {}

        # Simple dict unpack is fine here — the dynamic config is flat (no
        # nested dicts), so override values win without recursive merging.
        data = {**dynamic_file_defaults, **dynamic_file_override}

        # Older versions stored received values without checking them, so a
        # non-numeric value would stop the service from ever starting again. A
        # report interval of 0 or less would spin the report timer, and a
        # negative runtime limit is meaningless.
        for key, default in dynamic_file_defaults.items():
            value = data[key]
            if (
                not _is_number(value)
                or (key == "report_interval" and value <= 0)
                or (key == "battery_runtime_limit" and value < 0)
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
            # An empty file loads as None
            static_file_override = yaml.safe_load(static_file) or {}

        if not isinstance(static_file_override, dict):
            msg = f"{self._static_file} must contain a mapping of options"
            raise ConfigurationError(msg)

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
                "tls": {
                    "enabled": False,
                    "ca_certs": None,
                    "certfile": None,
                    "keyfile": None,
                    "insecure": False,
                },
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
                "power": {
                    "name": "power",
                    "pretty": "Power",
                    "type": "sensor",
                    "unit": "W",
                    "device_class": "power",
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
                "charging": {
                    "name": "charging",
                    "pretty": "Charging",
                    "type": "binary_sensor",
                    "device_class": "battery_charging",
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
                    # A bitmask, so long-term statistics would be meaningless
                    "state_class": None,
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
                    "pretty": "Battery shutdown level",
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
                "battery_runtime_limit": {
                    "name": "battery_runtime_limit",
                    "pretty": "Battery runtime limit",
                    "type": "number",
                    "unit": "min",
                    "device_class": "duration",
                    "entity_category": "diagnostic",
                    "min": 0,
                    "max": 1440,
                    "mode": "box",
                    "step": 1,
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
                "bus": DEFAULT_INA_I2C_BUS,
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

        errors = _validate_static(static_file_defaults)
        if errors:
            msg = f"Invalid configuration in {self._static_file}: " + "; ".join(
                errors,
            )
            raise ConfigurationError(msg)

        # MQTT brokers disconnect a client when another connects with the same
        # ID, so default to one that is unique per configured hostname
        static_file_defaults["mqtt"].setdefault(
            "client_id",
            f"redreactor-{static_file_defaults['hostname']['name']}",
        )

        return static_file_defaults
