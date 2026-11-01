"""CPU Utils.

Reads the CPU temperature and the Raspberry Pi throttling state on any Linux
system: Raspberry Pi OS, Ubuntu, Home Assistant OS (inside an add-on
container), and generic x86/ARM machines.

Each value is read from the most authoritative source available, falling back
to less precise sources, and every reader returns ``None`` instead of raising
when a source is missing, unreadable, or returns garbage.

Temperature sources, in order:
  1. ``/sys/class/thermal`` thermal zones, picking the zone whose ``type``
     names the CPU/SoC rather than assuming ``thermal_zone0`` is the CPU.
  2. ``/sys/class/hwmon`` CPU sensors (``cpu_thermal``, ``coretemp``,
     ``k10temp`` ...), which covers x86 machines without a CPU thermal zone.
  3. ``vcgencmd measure_temp`` (Raspberry Pi userland tools).

Throttling sources, in order:
  1. The firmware ``get_throttled`` sysfs attribute (Raspberry Pi kernels).
  2. ``vcgencmd get_throttled``.
  3. A bitmask built from what the kernel exposes on every Linux system: the
     upstream ``rpi_volt`` hwmon under-voltage alarm, cpufreq limits, and the
     CPU thermal zone's passive trip point.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

# Bit positions in the Raspberry Pi firmware throttling bitmask.
# Bits 0-3 reflect the CURRENT state; bits 16-19 reflect whether the condition
# has OCCURRED at any point since the last reboot (sticky history flags).
UNDER_VOLTAGE_BIT = 0
FREQ_CAPPED_BIT = 1
THROTTLED_BIT = 2
SOFT_TEMP_LIMIT_BIT = 3

# sysfs roots. Module level so tests can point them at a fake tree.
THERMAL_ROOT = Path("/sys/class/thermal")
HWMON_ROOT = Path("/sys/class/hwmon")
CPUFREQ_PATHS = [
    Path("/sys/devices/system/cpu/cpufreq/policy0"),
    Path("/sys/devices/system/cpu/cpu0/cpufreq"),
]

# Firmware throttle attribute. The path varies across Pi hardware revisions and
# kernel versions.
SYSFS_THROTTLE_PATHS = [
    Path("/sys/devices/platform/soc/soc:firmware/get_throttled"),
    Path("/sys/devices/platform/scb/soc:firmware/get_throttled"),
    Path("/sys/devices/platform/soc:firmware/get_throttled"),
]

# Thermal zone ``type`` values that identify the CPU or SoC, best first.
# Raspberry Pi kernels use "cpu-thermal"; x86 uses "x86_pkg_temp"; many ARM
# SoCs use "soc_thermal" or "cpu0-thermal"; "acpitz" is a last resort as it is
# often a motherboard sensor rather than the CPU die.
CPU_THERMAL_ZONE_TYPES = [
    "cpu-thermal",
    "cpu_thermal",
    "x86_pkg_temp",
    "soc-thermal",
    "soc_thermal",
    "cpu0-thermal",
    "cpu0_thermal",
    "cpu",
    "cpuss0-thermal",
    "acpitz",
]

# hwmon ``name`` values that identify a CPU temperature sensor, best first.
CPU_HWMON_NAMES = [
    "cpu_thermal",
    "cpu-thermal",
    "coretemp",
    "k10temp",
    "zenpower",
    "soc_thermal",
    "cpu0_thermal",
]

# hwmon labels that identify the whole-package reading on multi-sensor chips.
CPU_HWMON_PACKAGE_LABELS = ("package", "tctl", "tdie", "cpu")

# hwmon device registered by the upstream raspberrypi-hwmon driver; it is
# present on Raspberry Pi OS, Ubuntu and Home Assistant OS kernels alike.
RPI_VOLT_HWMON_NAME = "rpi_volt"

VCGENCMD_PATHS = [Path("/usr/bin/vcgencmd"), Path("/opt/vc/bin/vcgencmd")]
VCGENCMD_TIMEOUT = 5

# Readings outside this range (in °C) are treated as a broken sensor.
MIN_VALID_TEMPERATURE = -40.0
MAX_VALID_TEMPERATURE = 150.0


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


def _millidegrees_to_celsius(milli: int | None) -> float | None:
    if milli is None:
        return None
    celsius = round(milli / 1000.0, 2)
    if not MIN_VALID_TEMPERATURE <= celsius <= MAX_VALID_TEMPERATURE:
        return None
    return celsius


def _sorted_children(root: Path, prefix: str) -> list[Path]:
    """Return ``root/prefix*`` entries in numeric order (zone2 before zone10)."""
    try:
        entries = [p for p in root.iterdir() if p.name.startswith(prefix)]
    except OSError:
        return []

    def _key(p: Path) -> tuple[int, str]:
        suffix = p.name[len(prefix) :]
        return (int(suffix) if suffix.isdigit() else 1 << 30, p.name)

    return sorted(entries, key=_key)


def find_cpu_thermal_zone() -> Path | None:
    """Return the thermal zone directory that best represents the CPU.

    Prefers a zone whose ``type`` names the CPU/SoC. When no zone has a known
    type, falls back to the first zone that gives a valid reading, which keeps
    the old ``thermal_zone0`` behaviour on unfamiliar boards.
    """
    zones = [
        z
        for z in _sorted_children(THERMAL_ROOT, "thermal_zone")
        if _millidegrees_to_celsius(_read_int(z / "temp")) is not None
    ]
    if not zones:
        return None

    by_type: dict[str, Path] = {}
    for zone in zones:
        zone_type = (_read_text(zone / "type") or "").lower()
        by_type.setdefault(zone_type, zone)

    for wanted in CPU_THERMAL_ZONE_TYPES:
        if wanted in by_type:
            return by_type[wanted]

    return zones[0]


def read_cpu_temperature_sysfs() -> float | None:
    """Read CPU temperature from the CPU thermal zone."""
    zone = find_cpu_thermal_zone()
    if zone is None:
        return None
    return _millidegrees_to_celsius(_read_int(zone / "temp"))


def _read_hwmon_cpu_temperature(hwmon: Path) -> float | None:
    """Read the package (or first valid) temperature from one hwmon device."""
    inputs = sorted(hwmon.glob("temp*_input"))
    first_valid: float | None = None
    for temp_input in inputs:
        value = _millidegrees_to_celsius(_read_int(temp_input))
        if value is None:
            continue
        label_path = temp_input.with_name(
            temp_input.name.replace("_input", "_label"),
        )
        label = (_read_text(label_path) or "").lower()
        if label.startswith(CPU_HWMON_PACKAGE_LABELS):
            return value
        if first_valid is None:
            first_valid = value
    return first_valid


def read_cpu_temperature_hwmon() -> float | None:
    """Read CPU temperature from a CPU hwmon sensor."""
    by_name: dict[str, Path] = {}
    for hwmon in _sorted_children(HWMON_ROOT, "hwmon"):
        name = (_read_text(hwmon / "name") or "").lower()
        by_name.setdefault(name, hwmon)

    for wanted in CPU_HWMON_NAMES:
        if wanted in by_name:
            value = _read_hwmon_cpu_temperature(by_name[wanted])
            if value is not None:
                return value
    return None


def _find_vcgencmd() -> list[Path]:
    candidates: list[Path] = []
    on_path = shutil.which("vcgencmd")
    if on_path:
        candidates.append(Path(on_path))
    candidates.extend(p for p in VCGENCMD_PATHS if p not in candidates)
    return [p for p in candidates if p.exists()]


def _run_vcgencmd(command: str) -> str | None:
    """Run ``vcgencmd <command>`` and return the value after ``=``.

    vcgencmd fails (non-zero exit, or a "VCHI initialization failed" message)
    when the user cannot open /dev/vchiq or /dev/vcio, which is common on
    Ubuntu and in containers, so every failure is treated as "unavailable".
    """
    for bin_path in _find_vcgencmd():
        try:
            result = subprocess.run(  # noqa: S603
                [str(bin_path), command],
                capture_output=True,
                text=True,
                check=True,
                timeout=VCGENCMD_TIMEOUT,
            )
        except (subprocess.SubprocessError, OSError):
            continue

        _, sep, value = result.stdout.strip().partition("=")
        if sep and value:
            return value.strip()
    return None


def read_cpu_temperature_vcgencmd() -> float | None:
    """Read CPU temperature using vcgencmd."""
    value = _run_vcgencmd("measure_temp")
    if value is None:
        return None
    try:
        celsius = round(float(value.split("'")[0]), 2)
    except ValueError:
        return None
    if not MIN_VALID_TEMPERATURE <= celsius <= MAX_VALID_TEMPERATURE:
        return None
    return celsius


def read_cpu_temperature() -> float | None:
    """Unified fallback: thermal zone → hwmon → vcgencmd."""
    for method in (
        read_cpu_temperature_sysfs,
        read_cpu_temperature_hwmon,
        read_cpu_temperature_vcgencmd,
    ):
        value = method()
        if value is not None:
            return value
    return None


def read_cpu_stat_sysfs() -> int | None:
    """Read throttling status from the firmware sysfs attribute."""
    for p in SYSFS_THROTTLE_PATHS:
        txt = _read_text(p)
        if txt is None:
            continue
        try:
            return int(txt, 16)
        except ValueError:
            continue
    return None


def read_cpu_stat_vcgencmd() -> int | None:
    """Read throttling status via vcgencmd."""
    value = _run_vcgencmd("get_throttled")
    if value is None:
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None


def read_under_voltage_hwmon() -> bool | None:
    """Read the current under-voltage alarm from the ``rpi_volt`` hwmon device.

    Returns ``None`` when the device does not exist (not a Raspberry Pi, or a
    kernel without the raspberrypi-hwmon driver).
    """
    for hwmon in _sorted_children(HWMON_ROOT, "hwmon"):
        if _read_text(hwmon / "name") != RPI_VOLT_HWMON_NAME:
            continue
        alarm = _read_int(hwmon / "in0_lcrit_alarm")
        if alarm is not None:
            return alarm != 0
    return None


def _read_cpufreq() -> tuple[int | None, int | None]:
    """Return ``(scaling_max_freq, cpuinfo_max_freq)`` for the first CPU."""
    for base in CPUFREQ_PATHS:
        scaling_max = _read_int(base / "scaling_max_freq")
        cpuinfo_max = _read_int(base / "cpuinfo_max_freq")
        if scaling_max is not None or cpuinfo_max is not None:
            return scaling_max, cpuinfo_max
    return None, None


def _passive_trip_temperature(zone: Path) -> int | None:
    """Return the lowest ``passive`` trip point of a zone, in millidegrees.

    A passive trip point is where the kernel starts throttling the CPU. When
    no trip point is typed passive, trip point 0 is used as before.
    """
    passive: list[int] = []
    for trip_type in zone.glob("trip_point_*_type"):
        if _read_text(trip_type) != "passive":
            continue
        temp = _read_int(trip_type.with_name(trip_type.name[:-4] + "temp"))
        if temp is not None and temp > 0:
            passive.append(temp)
    if passive:
        return min(passive)
    trip0 = _read_int(zone / "trip_point_0_temp")
    return trip0 if trip0 is not None and trip0 > 0 else None


def read_cpu_stat_inferred() -> int | None:
    """Build a throttling bitmask from generic kernel interfaces.

    Used where the firmware attribute and vcgencmd are unavailable, such as
    Home Assistant OS add-ons, Ubuntu, and non-Raspberry Pi hardware.

    Sets:
      Bit 0 (under-voltage) from the ``rpi_volt`` hwmon alarm
      Bit 1 (frequency capped) when cpufreq's limit is below the hardware max
      Bit 3 (soft temp limit) when the CPU is at its passive trip point

    The history bits (16-19) cannot be inferred and are never set.
    Returns ``None`` only when none of the inputs could be read.
    """
    under_voltage = read_under_voltage_hwmon()
    scaling_max, cpuinfo_max = _read_cpufreq()

    zone = find_cpu_thermal_zone()
    current_temp = _read_int(zone / "temp") if zone is not None else None
    trip_temp = _passive_trip_temperature(zone) if zone is not None else None

    if all(
        v is None
        for v in (under_voltage, scaling_max, cpuinfo_max, current_temp, trip_temp)
    ):
        return None

    mask = 0

    if under_voltage:
        mask |= 1 << UNDER_VOLTAGE_BIT

    # BIT 1: Frequency capped — scaling_max more than 5% below the hardware
    # ceiling is a reliable sign that a cap has been imposed.
    if (
        cpuinfo_max is not None
        and scaling_max is not None
        and scaling_max < int(cpuinfo_max * 0.95)
    ):
        mask |= 1 << FREQ_CAPPED_BIT

    # BIT 3: Soft thermal throttle
    if current_temp is not None and trip_temp is not None and current_temp >= trip_temp:
        mask |= 1 << SOFT_TEMP_LIMIT_BIT

    return mask


def read_cpu_stat() -> int | None:
    """Unified throttling fallback: firmware sysfs → vcgencmd → inferred."""
    for method in (
        read_cpu_stat_sysfs,
        read_cpu_stat_vcgencmd,
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

    # +16 accesses the sticky "has occurred since boot" history flags.
    if value & (1 << (UNDER_VOLTAGE_BIT + 16)):
        messages.append("Under-voltage OCCURRED")
    if value & (1 << (FREQ_CAPPED_BIT + 16)):
        messages.append("Frequency capped OCCURRED")
    if value & (1 << (THROTTLED_BIT + 16)):
        messages.append("Throttling OCCURRED")
    if value & (1 << (SOFT_TEMP_LIMIT_BIT + 16)):
        messages.append("Soft temp limit OCCURRED")

    return ", ".join(messages) if messages else "OK"
