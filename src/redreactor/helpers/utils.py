"""Utils."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import requests


def dict_merge(dct: Any, merge_dct: dict[str, Any]) -> None:
    """Recursive dict merge.

    Inspired by :meth:``dict.update()``, instead of
    updating only top-level keys, dict_merge recurses down into dicts nested
    to an arbitrary depth, updating keys. The ``merge_dct`` is merged into
    ``dct``.
    :param dct: dict onto which the merge is executed
    :param merge_dct: dct merged into dct
    :return: None.
    """
    for k in merge_dct:
        if k in dct and isinstance(dct[k], dict) and isinstance(merge_dct[k], dict):
            dict_merge(dct[k], merge_dct[k])
        else:
            dct[k] = merge_dct[k]


def read_cpu_temperature_sysfs() -> float | None:
    """Read CPU Temperature using Sysfs."""
    paths = [
        Path("/sys/class/thermal/thermal_zone0/temp"),
        Path("/sys/devices/virtual/thermal/thermal_zone0/temp"),
    ]

    for p in paths:
        if p.exists():
            try:
                with p.open("r") as f:
                    milli = int(f.read().strip())
                    return round(milli / 1000.0, 2)
            except (OSError, ValueError):
                continue

    return None


def read_cpu_temperature_vcgencmd() -> float | None:
    """Read CPU Temperature using Vcgencmd."""
    bins = [Path("/usr/bin/vcgencmd"), Path("/opt/vc/bin/vcgencmd")]

    for binary in bins:
        if binary.exists() and binary.is_file():
            try:
                result = subprocess.run(  # noqa: S603
                    [str(binary), "measure_temp"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                temp_str = result.stdout.split("=")[1].split("'")[0]
                return round(float(temp_str), 2)
            except (
                subprocess.CalledProcessError,
                FileNotFoundError,
                IndexError,
                ValueError,
            ):
                continue

    return None


def read_cpu_stat_sysfs() -> int | None:
    """Read CPU Stat using Sysfs."""
    paths = [
        Path("/sys/devices/platform/soc/soc:firmware/get_throttled"),
        Path("/sys/devices/platform/scb/soc:firmware/get_throttled"),
        Path("/sys/firmware/devicetree/base/soc/get_throttled"),
    ]

    for p in paths:
        if p.exists():
            try:
                with p.open("r") as f:
                    return int(f.read().strip(), 16)
            except (OSError, ValueError):
                continue

    return None


def read_cpu_stat_vcgencmd() -> int | None:
    """Read CPU Stat using Vcgencmd."""
    bins = [Path("/usr/bin/vcgencmd"), Path("/opt/vc/bin/vcgencmd")]

    for binary in bins:
        if binary.exists() and binary.is_file():
            try:
                result = subprocess.run(  # noqa: S603
                    [str(binary), "get_throttled"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                hex_str = result.stdout.split("=")[1].strip()
                return int(hex_str, 16)
            except (
                subprocess.CalledProcessError,
                FileNotFoundError,
                IndexError,
                ValueError,
            ):
                continue

    return None


def read_cpu_stat_hassos() -> int | None:
    """Read CPU throttling via HassOS (Supervisor API)."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None

    url = "http://supervisor/hardware/info"

    try:
        response = requests.get(
            url,
            timeout=5,
            headers={"Authorization": f"Bearer {token}"},
        )
        data = response.json()
    except (requests.RequestException, ValueError, json.JSONDecodeError):
        return None

    throttling = data.get("data", {}).get("chassis", {}).get("throttling")

    if not isinstance(throttling, dict):
        return None

    mask = 0

    if throttling.get("under_voltage"):
        mask |= 1 << 0
    if throttling.get("frequency_capped"):
        mask |= 1 << 1
    if throttling.get("throttled"):
        mask |= 1 << 2
    if throttling.get("soft_temp_limit"):
        mask |= 1 << 3

    return mask


def decode_cpu_stat_text(value: int) -> str:
    """Decode CPU Stat information into readable text."""
    messages = []

    if value & (1 << 0):
        messages.append("Under-voltage NOW")
    if value & (1 << 1):
        messages.append("Frequency Capped NOW")
    if value & (1 << 2):
        messages.append("Currently Throttled")
    if value & (1 << 3):
        messages.append("Soft Temp Limit NOW")

    if value & (1 << 16):
        messages.append("Under-voltage OCCURRED")
    if value & (1 << 17):
        messages.append("Frequency Capped OCCURRED")
    if value & (1 << 18):
        messages.append("Throttling OCCURRED")
    if value & (1 << 19):
        messages.append("Soft Temp Limit OCCURRED")

    return ", ".join(messages) if messages else "OK"
