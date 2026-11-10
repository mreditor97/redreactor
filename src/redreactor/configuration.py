"""Configuration module.

Contains the ability to read the static and dynamic configuration files.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import re
import shlex
from itertools import pairwise
from pathlib import Path
from typing import Any

import yaml

from redreactor.const import (
    BATTERY_AVERAGE_READINGS_MAXIMUM,
    DEFAULT_BATTERY_AVERAGE_READINGS,
    DEFAULT_BATTERY_INTERNAL_RESISTANCE,
    DEFAULT_BATTERY_REPORT_LEVEL_CHANGE,
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP,
    DEFAULT_BATTERY_VOLTAGE_MINIMUM,
    DEFAULT_INA_ADC_SAMPLES,
    DEFAULT_INA_I2C_ADDRESS,
    DEFAULT_INA_I2C_BUS,
    DEFAULT_INA_MAX_EXPECTED_AMPS,
    DEFAULT_INA_MONITOR_INTERVAL,
    DEFAULT_INA_SHUNT_OHMS,
    DYNAMIC_SETTINGS,
    INA_ADC_SAMPLES,
    POWER_EVENT_TYPES,
)
from redreactor.helpers.emitter import EventEmitter
from redreactor.helpers.utils import dict_merge

logger = logging.getLogger("Red Reactor")

# Valid 7-bit I2C addresses, 0x00-0x02 and 0x78-0x7F are reserved
I2C_ADDRESS_MINIMUM = 0x03
I2C_ADDRESS_MAXIMUM = 0x77
PORT_MAXIMUM = 65535
# MQTT sends the keepalive as a 16 bit number of seconds
KEEPALIVE_MAXIMUM = 65535
# Monitor and discovery intervals, in seconds. A tiny interval spins a timer
# thread, and a huge one overflows the timer
MONITOR_INTERVAL_MINIMUM = 0.1
DISCOVERY_INTERVAL_MINIMUM = 1
INTERVAL_MAXIMUM = 86400

FIELD_TYPES = frozenset({"sensor", "binary_sensor", "number", "button", "event"})
MQTT_TRANSPORTS = frozenset({"tcp", "websockets", "unix"})
# Field names are used as MQTT topic levels, JSON keys and in the Home
# Assistant template `{{ value_json.<name> }}`, so they must be identifiers
FIELD_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


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
        ("ina", "adc_samples"),
        ("battery", "internal_resistance"),
        ("battery", "average_readings"),
        ("battery", "report_level_change"),
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


def _validate_static(configuration: dict[str, Any]) -> list[str]:  # noqa: C901
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
        "battery",
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

    errors.extend(_validate_fields(configuration["fields"]))
    if errors:
        # The remaining checks and the defaults below read each field
        return errors

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
        _is_number(mqtt["timeout"]) and 0 <= mqtt["timeout"] <= KEEPALIVE_MAXIMUM,
        f"must be a number of seconds from 0 to {KEEPALIVE_MAXIMUM}",
    )
    check(
        "mqtt.transport",
        mqtt["transport"] in MQTT_TRANSPORTS,
        f"must be one of {', '.join(sorted(MQTT_TRANSPORTS))}",
    )
    check(
        "mqtt.broker",
        isinstance(mqtt["broker"], str) and mqtt["broker"].strip() != "",
        "must be a host name or address",
    )
    # Text or left out, paho calls len() and encode() on these
    for key in ("user", "password", "client_id"):
        if key in mqtt:
            check(
                f"mqtt.{key}",
                mqtt[key] is None or isinstance(mqtt[key], str),
                "must be text",
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
    errors.extend(_validate_battery_curve(configuration["battery"]["curve"]))

    check(
        "ina.monitor_interval",
        _is_number(ina["monitor_interval"])
        and MONITOR_INTERVAL_MINIMUM <= ina["monitor_interval"] <= INTERVAL_MAXIMUM,
        f"must be a number of seconds from {MONITOR_INTERVAL_MINIMUM} to "
        f"{INTERVAL_MAXIMUM}",
    )
    # 0 turns the repeated discovery off, it is still sent on connect and when
    # Home Assistant comes online
    discovery_interval = homeassistant["discovery_interval"]
    check(
        "homeassistant.discovery_interval",
        _is_number(discovery_interval)
        and (
            discovery_interval == 0
            or DISCOVERY_INTERVAL_MINIMUM <= discovery_interval <= INTERVAL_MAXIMUM
        ),
        f"must be 0 (off) or a number of seconds from {DISCOVERY_INTERVAL_MINIMUM} "
        f"to {INTERVAL_MAXIMUM}",
    )
    check(
        "ina.adc_samples",
        not isinstance(ina["adc_samples"], bool)
        and isinstance(ina["adc_samples"], int)
        and ina["adc_samples"] in INA_ADC_SAMPLES,
        "must be one of " + ", ".join(str(n) for n in INA_ADC_SAMPLES),
    )

    # Positive numbers
    for path, value in (
        ("ina.shunt_ohms", ina["shunt_ohms"]),
        ("ina.max_expected_amps", ina["max_expected_amps"]),
    ):
        check(path, _is_number(value) and value > 0, "must be a number above 0")
    check(
        "battery.average_readings",
        not isinstance(configuration["battery"]["average_readings"], bool)
        and isinstance(configuration["battery"]["average_readings"], int)
        and 1
        <= configuration["battery"]["average_readings"]
        <= BATTERY_AVERAGE_READINGS_MAXIMUM,
        f"must be a whole number from 1 to {BATTERY_AVERAGE_READINGS_MAXIMUM}",
    )
    check(
        "battery.report_level_change",
        _is_number(configuration["battery"]["report_level_change"])
        and 0
        <= configuration["battery"]["report_level_change"]
        <= 100,  # noqa: PLR2004
        "must be a number of percentage points from 0 to 100, 0 turns it off",
    )
    check(
        "battery.internal_resistance",
        _is_number(configuration["battery"]["internal_resistance"])
        and configuration["battery"]["internal_resistance"] >= 0,
        "must be a number of milliohms, 0 or more",
    )
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
        ("homeassistant.status_topic", homeassistant["status_topic"], True),
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

    # Payloads compared with, or published as, MQTT text
    for path, value in (
        ("homeassistant.status_online", homeassistant["status_online"]),
        ("status.online", configuration["status"]["online"]),
        ("status.offline", configuration["status"]["offline"]),
        ("hostname.pretty", configuration["hostname"]["pretty"]),
    ):
        check(path, isinstance(value, str) and value != "", "must be text")
    check(
        "status.offline",
        configuration["status"]["online"] != configuration["status"]["offline"],
        "must be different to `status.online`",
    )

    # Checked here, a command that can't be split would otherwise only fail
    # once the battery is already low
    for path, value in (
        ("system.shutdown", configuration["system"]["shutdown"]),
        ("system.restart", configuration["system"]["restart"]),
    ):
        check(path, _is_command(value), "must be a command")

    return errors


def _is_command(value: Any) -> bool:
    """Check for a command that shlex can split into at least one argument."""
    if not isinstance(value, str):
        return False
    try:
        return bool(shlex.split(value))
    except ValueError:
        # An unbalanced quote or a trailing escape
        return False


def _validate_fields(fields: dict[str, Any]) -> list[str]:
    """Check each field is a mapping with a usable name and type.

    A new field must give both, and an existing one can't be replaced with a
    plain value, as every field is read as a mapping.
    """
    errors = []
    for key, field in fields.items():
        if not isinstance(field, dict):
            errors.append(f"`fields.{key}` must be a mapping, got {field!r}")
            continue
        name = field.get("name")
        if not isinstance(name, str) or not FIELD_NAME_PATTERN.fullmatch(name):
            errors.append(
                f"`fields.{key}.name` must be letters, digits and _, not starting "
                f"with a digit, got {name!r}",
            )
        errors.extend(
            f"`fields.{key}.{limit}` must be a number, got {field[limit]!r}"
            for limit in ("min", "max", "step")
            if field.get(limit) is not None and not _is_number(field[limit])
        )
        if field.get("type") not in FIELD_TYPES:
            errors.append(
                f"`fields.{key}.type` must be one of "
                f"{', '.join(sorted(FIELD_TYPES))}, got {field.get('type')!r}",
            )
    return errors


def _validate_battery_curve(curve: Any) -> list[str]:
    """Check the battery curve is usable for interpolation.

    The voltages must rise and the levels must not fall, so each voltage maps
    to one battery level.
    """
    if curve is None:
        return []

    requirement = (
        "`battery.curve` must be a list of at least 2 [voltage, level] pairs, "
        "with rising voltages and levels from 0 to 100 that don't fall"
    )
    if (
        not isinstance(curve, list)
        or len(curve) < 2  # noqa: PLR2004
        or not all(
            isinstance(point, list)
            and len(point) == 2  # noqa: PLR2004
            and all(_is_number(value) for value in point)
            and 0 <= point[1] <= 100  # noqa: PLR2004
            for point in curve
        )
    ):
        return [f"{requirement}, got {curve!r}"]

    for (voltage, level), (next_voltage, next_level) in pairwise(curve):
        if next_voltage <= voltage or next_level < level:
            return [f"{requirement}, got {curve!r}"]

    return []


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

    def __init__(
        self,
        dynamic_file: str,
        fields: dict[str, Any] | None = None,
        static_defaults: dict[str, Any] | None = None,
    ) -> None:
        """Initialise the Dynamic Configuration object.

        `fields` is the static field configuration, used to range check the
        stored values against each number's `min` and `max`.

        `static_defaults` are settings whose default comes from the static
        configuration, such as the monitor interval. They are only saved while
        they differ from it, so a change to the static file still applies until
        the setting is changed from MQTT, and setting it back to the static
        value hands it back to the static file.
        """
        self._dynamic_file = dynamic_file
        self._fields = fields or {}
        self._static_defaults = static_defaults or {}
        self.event = EventEmitter()

        self.data = self._load()

        # Self-register so any component can persist a config change simply by
        # emitting "write" on this event, without needing a direct reference.
        self.event.on(event_name="write", function=self.write)

    def _load(self) -> Any:
        """Load dynamic configuration file."""
        dynamic_file_defaults: dict[str, Any] = {
            key: default for key, (_, default) in DYNAMIC_SETTINGS.items()
        } | self._static_defaults

        dynamic_path = Path(self._dynamic_file)
        dynamic_file_override: Any = {}
        if not dynamic_path.exists():
            # Without the file the defaults are used, and the low battery
            # shutdown still works, so a missing folder or read-only storage
            # must not stop the service
            try:
                with dynamic_path.open("w") as file:
                    json.dump(self._saved(dynamic_file_defaults), file)
            except OSError as error:
                logger.warning(
                    "Unable to create %s (%s), using the default settings, "
                    "changes made from MQTT won't be kept after a restart",
                    self._dynamic_file,
                    error,
                )
        else:
            try:
                with dynamic_path.open() as file:
                    dynamic_file_override = json.load(file)
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
                logger.warning(
                    "Unable to read %s (%s), using the default settings",
                    self._dynamic_file,
                    error,
                )

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
        # negative capacity is meaningless.
        for key, default in dynamic_file_defaults.items():
            if key in self._static_defaults and key not in dynamic_file_override:
                # Checked with the static configuration already
                continue
            value = data[key]
            field = self._fields.get(key) or {}
            minimum = field.get("min")
            maximum = field.get("max")
            if (
                not _is_number(value)
                or (key in {"report_interval", "monitor_interval"} and value <= 0)
                or (key in {"average_readings", "shutdown_readings"} and value < 1)
                or (key == "battery_capacity" and value < 0)
                # The same range a value received over MQTT is checked against
                or (_is_number(minimum) and value < minimum)
                or (_is_number(maximum) and value > maximum)
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

    def _saved(self, data: dict[str, Any]) -> dict[str, Any]:
        """Return the settings to save, leaving out unchanged static defaults."""
        return {
            key: value
            for key, value in data.items()
            if key not in self._static_defaults or value != self._static_defaults[key]
        }

    def write(self) -> None:
        """Write dynamic configuration file.

        Written to a temporary file and then renamed over the original, so a
        power cut part way through can't leave a truncated file behind.
        """
        dynamic_path = Path(self._dynamic_file)
        temporary_path = dynamic_path.with_name(f"{dynamic_path.name}.tmp")
        try:
            with temporary_path.open("w") as file:
                json.dump(self._saved(self.data), file)
                file.flush()
                os.fsync(file.fileno())
            temporary_path.replace(dynamic_path)
        except OSError as error:
            # The new value is still used until the service restarts. This is
            # called from the MQTT thread, so it must not raise.
            logger.error(  # noqa: TRY400
                "Unable to save the settings to %s (%s), the change is used "
                "but won't be kept after a restart",
                self._dynamic_file,
                error,
            )


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
        self.dynamic = DynamicConfiguration(
            self._dynamic_file,
            self.static["fields"],
            static_defaults={
                "monitor_interval": self.static["ina"]["monitor_interval"],
                "average_readings": self.static["battery"]["average_readings"],
            },
        )

    def _load(self) -> dict[str, Any]:
        """Load static configuration file, and override defaults."""
        try:
            with Path(self._static_file).open() as static_file:
                # An empty file loads as None
                static_file_override = yaml.safe_load(static_file) or {}
        except OSError as error:
            msg = f"Unable to read {self._static_file}: {error.strerror or error}"
            raise ConfigurationError(msg) from error
        except yaml.YAMLError as error:
            msg = f"{self._static_file} is not valid YAML: {error}"
            raise ConfigurationError(msg) from error

        if not isinstance(static_file_override, dict):
            msg = f"{self._static_file} must contain a mapping of options"
            raise ConfigurationError(msg)

        static_file_defaults: dict[str, Any] = {
            "mqtt": {
                "broker": "127.0.0.1",
                "port": 1883,
                # Empty connects anonymously, set both for a broker with logins
                "user": "",
                "password": "",
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
                    "event": "event",
                },
                "exit_on_fail": True,
            },
            "hostname": {"name": "redreactor", "pretty": "Red Reactor"},
            "homeassistant": {
                "discovery": True,
                "topic": "homeassistant",
                "status_topic": "homeassistant/status",
                "status_online": "online",
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
                "under_voltage": {
                    "name": "under_voltage",
                    "pretty": "Under-voltage",
                    "type": "binary_sensor",
                    "device_class": "problem",
                    "entity_category": "diagnostic",
                },
                "throttled": {
                    "name": "throttled",
                    "pretty": "Throttled",
                    "type": "binary_sensor",
                    "device_class": "problem",
                    "entity_category": "diagnostic",
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
                "battery_capacity": {
                    "name": "battery_capacity",
                    "pretty": "Battery capacity",
                    "type": "number",
                    "unit": "mAh",
                    "entity_category": "diagnostic",
                    "min": 0,
                    "max": 20000,
                    "mode": "box",
                    "step": 1,
                },
                "monitor_interval": {
                    "name": "monitor_interval",
                    "pretty": "Monitor interval",
                    "type": "number",
                    "unit": "s",
                    "entity_category": "diagnostic",
                    "min": 0.5,
                    "max": 300,
                    "mode": "box",
                    "step": 0.5,
                },
                "average_readings": {
                    "name": "average_readings",
                    "pretty": "Readings averaged",
                    "type": "number",
                    "entity_category": "diagnostic",
                    "min": 1,
                    "max": BATTERY_AVERAGE_READINGS_MAXIMUM,
                    "mode": "box",
                    "step": 1,
                },
                "shutdown_readings": {
                    "name": "shutdown_readings",
                    "pretty": "Shutdown confirmation readings",
                    "type": "number",
                    "entity_category": "diagnostic",
                    "min": 1,
                    "max": 20,
                    "mode": "box",
                    "step": 1,
                },
                "battery_time_remaining": {
                    "name": "battery_time_remaining",
                    "pretty": "Battery time remaining",
                    "type": "sensor",
                    "unit": "d",
                    "device_class": "duration",
                    "suggested_display_precision": 1,
                },
                "sensor_problem": {
                    "name": "sensor_problem",
                    "pretty": "Sensor problem",
                    "type": "binary_sensor",
                    "device_class": "problem",
                    "entity_category": "diagnostic",
                },
                "last_shutdown": {
                    "name": "last_shutdown",
                    "pretty": "Last shutdown",
                    "type": "sensor",
                    "entity_category": "diagnostic",
                    "state_class": None,
                },
                "last_shutdown_time": {
                    "name": "last_shutdown_time",
                    "pretty": "Last shutdown time",
                    "type": "sensor",
                    "device_class": "timestamp",
                    "entity_category": "diagnostic",
                    "state_class": None,
                },
                "last_shutdown_voltage": {
                    "name": "last_shutdown_voltage",
                    "pretty": "Last shutdown voltage",
                    "type": "sensor",
                    "unit": "V",
                    "device_class": "voltage",
                    "entity_category": "diagnostic",
                    "state_class": None,
                    "suggested_display_precision": 2,
                },
                "power_event": {
                    "name": "power_event",
                    "pretty": "Power event",
                    "type": "event",
                    "event_types": list(POWER_EVENT_TYPES),
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
                "refresh": {
                    "name": "refresh",
                    "pretty": "Refresh",
                    "type": "button",
                    "entity_category": "diagnostic",
                },
            },
            "ina": {
                "address": DEFAULT_INA_I2C_ADDRESS,
                "shunt_ohms": DEFAULT_INA_SHUNT_OHMS,
                "max_expected_amps": DEFAULT_INA_MAX_EXPECTED_AMPS,
                "monitor_interval": DEFAULT_INA_MONITOR_INTERVAL,
                # Samples the INA219 averages for each reading, 1 is a single
                # 12-bit sample
                "adc_samples": DEFAULT_INA_ADC_SAMPLES,
                "bus": DEFAULT_INA_I2C_BUS,
            },
            "battery": {
                # Milliohms, used to correct the voltage for the sag under load
                "internal_resistance": DEFAULT_BATTERY_INTERNAL_RESISTANCE,
                # Monitor readings averaged for the battery level, 1 turns it off
                "average_readings": DEFAULT_BATTERY_AVERAGE_READINGS,
                # Pairs of [resting voltage, battery level %], None uses a
                # straight line between the minimum and maximum voltage
                "curve": None,
                # Battery level change, in percentage points, reported straight
                # away instead of at the next report interval, 0 turns it off
                "report_level_change": DEFAULT_BATTERY_REPORT_LEVEL_CHANGE,
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
