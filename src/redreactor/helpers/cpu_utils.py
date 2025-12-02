"""CPU Utils."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import requests

UNDER_VOLTAGE_BIT = 0
FREQ_CAPPED_BIT = 1
THROTTLED_BIT = 2
SOFT_TEMP_LIMIT_BIT = 3

SYSFS_TEMP_PATHS = [
    Path("/sys/class/thermal/thermal_zone0/temp"),
    Path("/sys/devices/virtual/thermal/thermal_zone0/temp"),
]

SYSFS_THROTTLE_PATHS = [
    Path("/sys/devices/platform/soc/soc:firmware/get_throttled"),
    Path("/sys/devices/platform/scb/soc:firmware/get_throttled"),
    Path("/sys/firmware/devicetree/base/soc/get_throttled"),
]

CPUFREQ_BASE = Path("/sys/devices/system/cpu/cpu0/cpufreq")
THERMAL_BASE = Path("/sys/class/thermal/thermal_zone0")


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except (OSError, UnicodeDecodeError):
        return None


def _read_int(path: Path) -> int | None:
    txt = _read_text(path)
    if txt is None:
        return None
    try:
        return int(txt)
    except ValueError:
        return None


def read_cpu_temperature_sysfs() -> float | None:
    """Read CPU temperature from sysfs."""
    for p in SYSFS_TEMP_PATHS:
        if p.exists():
            milli = _read_int(p)
            if milli is not None:
                return round(milli / 1000.0, 2)
    return None


def read_cpu_temperature_vcgencmd() -> float | None:
    """Read CPU temperature using vcgencmd."""
    for bin_path in (Path("/usr/bin/vcgencmd"), Path("/opt/vc/bin/vcgencmd")):
        if not bin_path.exists():
            continue

        try:
            result = subprocess.run(  # noqa: S603
                [str(bin_path), "measure_temp"],
                capture_output=True,
                text=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

        try:
            temp_str = result.stdout.split("=")[1].split("'")[0]
            return round(float(temp_str), 2)
        except (IndexError, ValueError):
            continue

    return None


def read_cpu_temperature() -> float | None:
    """Unified fallback: sysfs → vcgencmd."""
    temp = read_cpu_temperature_sysfs()
    if temp is not None:
        return temp

    return read_cpu_temperature_vcgencmd()


def read_cpu_stat_sysfs() -> int | None:
    """Read throttling status from sysfs firmware exports."""
    for p in SYSFS_THROTTLE_PATHS:
        if p.exists():
            try:
                return int(p.read_text().strip(), 16)
            except (OSError, ValueError):
                continue
    return None


def read_cpu_stat_vcgencmd() -> int | None:
    """Read throttling status via vcgencmd."""
    for bin_path in (Path("/usr/bin/vcgencmd"), Path("/opt/vc/bin/vcgencmd")):
        if not bin_path.exists():
            continue

        try:
            result = subprocess.run(  # noqa: S603
                [str(bin_path), "get_throttled"],
                capture_output=True,
                text=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

        try:
            hex_str = result.stdout.split("=")[1].strip()
            return int(hex_str, 16)
        except (IndexError, ValueError):
            continue

    return None


def read_cpu_stat_hassos() -> int | None:
    """Read throttling info via HassOS Supervisor (if available)."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None

    try:
        response = requests.get(
            "http://supervisor/hardware/info",
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
        mask |= 1 << UNDER_VOLTAGE_BIT
    if throttling.get("frequency_capped"):
        mask |= 1 << FREQ_CAPPED_BIT
    if throttling.get("throttled"):
        mask |= 1 << THROTTLED_BIT
    if throttling.get("soft_temp_limit"):
        mask |= 1 << SOFT_TEMP_LIMIT_BIT

    return mask


def read_cpu_stat_inferred() -> int | None:
    """Infer throttling using CPU frequency scaling and thermal data.

    Works on Raspberry Pi 4/5 with modern HassOS where:
      - vcgencmd is unavailable
      - Supervisor has no throttling info
      - sysfs get_throttled does not exist

    Sets:
      Bit 1 (frequency capped)
      Bit 3 (soft temp limit)
    """
    # Read cpufreq values
    current_freq = _read_int(CPUFREQ_BASE / "scaling_cur_freq")
    scaling_max = _read_int(CPUFREQ_BASE / "scaling_max_freq")
    cpuinfo_max = _read_int(CPUFREQ_BASE / "cpuinfo_max_freq")

    # Read thermal values
    current_temp = _read_int(THERMAL_BASE / "temp")
    trip0_temp = _read_int(THERMAL_BASE / "trip_point_0_temp")

    # Return None if ALL data is missing (SIM102 clean)
    if all(
        v is None
        for v in (current_freq, scaling_max, cpuinfo_max, current_temp, trip0_temp)
    ):
        return None

    mask = 0

    # BIT 1: Frequency capped (merged for SIM102)
    if (
        cpuinfo_max is not None
        and scaling_max is not None
        and scaling_max < int(cpuinfo_max * 0.95)
    ):
        mask |= 1 << FREQ_CAPPED_BIT

    # BIT 3: Soft thermal throttle (merged for SIM102)
    if (
        current_temp is not None
        and trip0_temp is not None
        and current_temp >= trip0_temp
    ):
        mask |= 1 << SOFT_TEMP_LIMIT_BIT

    return mask or None


def read_cpu_stat() -> int | None:
    """Unified throttling fallback."""
    for method in (
        read_cpu_stat_sysfs,
        read_cpu_stat_vcgencmd,
        read_cpu_stat_hassos,
        read_cpu_stat_inferred,
    ):
        value = method()
        if value is not None:
            return value
    return None


def decode_cpu_stat_text(value: int) -> str:
    """Convert throttling bitmask to human-friendly text."""
    messages = []

    if value & (1 << UNDER_VOLTAGE_BIT):
        messages.append("Under-voltage NOW")
    if value & (1 << FREQ_CAPPED_BIT):
        messages.append("Frequency capped NOW")
    if value & (1 << THROTTLED_BIT):
        messages.append("Throttled NOW")
    if value & (1 << SOFT_TEMP_LIMIT_BIT):
        messages.append("Soft temp limit NOW")

    if value & (1 << (UNDER_VOLTAGE_BIT + 16)):
        messages.append("Under-voltage OCCURRED")
    if value & (1 << (FREQ_CAPPED_BIT + 16)):
        messages.append("Frequency capped OCCURRED")
    if value & (1 << (THROTTLED_BIT + 16)):
        messages.append("Throttling OCCURRED")
    if value & (1 << (SOFT_TEMP_LIMIT_BIT + 16)):
        messages.append("Soft temp limit OCCURRED")

    return ", ".join(messages) if messages else "OK"
