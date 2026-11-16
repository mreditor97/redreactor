"""The entities published to Home Assistant, and their state keys.

Each field is one entity. The key names it in the code, and its `name` is used
in the MQTT topics and the state JSON. Any of these can be changed, or more
options added, from `fields` in the configuration file.
"""

from __future__ import annotations

from typing import Any

from redreactor.const import POWER_EVENT_TYPES


def default_fields() -> dict[str, dict[str, Any]]:
    """Return the default fields, a new copy each time as it is merged into."""
    return {
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
        "battery_time_remaining": {
            "name": "battery_time_remaining",
            "pretty": "Battery time remaining",
            "type": "sensor",
            "unit": "d",
            "device_class": "duration",
            "suggested_display_precision": 1,
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
    }
