"""Tests for cpu_utils.

Most tests build a fake sysfs tree in ``tmp_path`` shaped like the real one on
the platform being simulated (Raspberry Pi OS, Home Assistant OS, Ubuntu x86,
a VM with no sensors) and point the module's sysfs roots at it.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from redreactor.helpers import cpu_utils
from redreactor.helpers.cpu_utils import (
    FREQ_CAPPED_BIT,
    SOFT_TEMP_LIMIT_BIT,
    UNDER_VOLTAGE_BIT,
    decode_cpu_stat_text,
    find_cpu_thermal_zone,
    read_cpu_stat,
    read_cpu_stat_inferred,
    read_cpu_stat_sysfs,
    read_cpu_stat_vcgencmd,
    read_cpu_temperature,
    read_cpu_temperature_hwmon,
    read_cpu_temperature_sysfs,
    read_cpu_temperature_vcgencmd,
    read_under_voltage_hwmon,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Fake sysfs helpers
# ---------------------------------------------------------------------------


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content + "\n")


def _zone(  # noqa: PLR0913
    root: Path,
    index: int,
    zone_type: str,
    temp: int | str,
    trips: list[tuple[str, int]] | None = None,
) -> Path:
    zone = root / "thermal" / f"thermal_zone{index}"
    _write(zone / "type", zone_type)
    _write(zone / "temp", str(temp))
    for n, (trip_type, trip_temp) in enumerate(trips or []):
        _write(zone / f"trip_point_{n}_type", trip_type)
        _write(zone / f"trip_point_{n}_temp", str(trip_temp))
    return zone


def _hwmon(root: Path, index: int, name: str, files: dict[str, str]) -> Path:
    hwmon = root / "hwmon" / f"hwmon{index}"
    _write(hwmon / "name", name)
    for filename, content in files.items():
        _write(hwmon / filename, content)
    return hwmon


def _cpufreq(root: Path, scaling_max: int, cpuinfo_max: int) -> None:
    policy = root / "cpufreq" / "policy0"
    _write(policy / "scaling_max_freq", str(scaling_max))
    _write(policy / "cpuinfo_max_freq", str(cpuinfo_max))


@pytest.fixture
def sysfs(tmp_path, monkeypatch):
    """Point every sysfs root at an empty fake tree and hide vcgencmd."""
    monkeypatch.setattr(cpu_utils, "THERMAL_ROOT", tmp_path / "thermal")
    monkeypatch.setattr(cpu_utils, "HWMON_ROOT", tmp_path / "hwmon")
    monkeypatch.setattr(
        cpu_utils,
        "CPUFREQ_PATHS",
        [tmp_path / "cpufreq" / "policy0"],
    )
    monkeypatch.setattr(
        cpu_utils,
        "SYSFS_THROTTLE_PATHS",
        [tmp_path / "firmware" / "get_throttled"],
    )
    monkeypatch.setattr(cpu_utils, "VCGENCMD_PATHS", [tmp_path / "bin" / "vcgencmd"])
    monkeypatch.setattr(cpu_utils.shutil, "which", lambda _name: None)
    return tmp_path


@pytest.fixture
def fake_vcgencmd(sysfs):
    """Make vcgencmd appear to exist; the test mocks subprocess.run."""
    _write(sysfs / "bin" / "vcgencmd", "#!/bin/sh")
    return sysfs / "bin" / "vcgencmd"


# ---------------------------------------------------------------------------
# Thermal zone selection
# ---------------------------------------------------------------------------


def test_raspberry_pi_cpu_thermal_zone(sysfs):
    """Raspberry Pi OS / HassOS: thermal_zone0 is cpu-thermal."""
    _zone(sysfs, 0, "cpu-thermal", 48312)
    assert read_cpu_temperature_sysfs() == 48.31


def test_cpu_zone_preferred_over_zone0(sysfs):
    """Ubuntu x86: zone0 is acpitz (board sensor), the CPU is x86_pkg_temp."""
    _zone(sysfs, 0, "acpitz", 27800)
    _zone(sysfs, 1, "INT3400 Thermal", 20000)
    _zone(sysfs, 2, "x86_pkg_temp", 55000)
    assert read_cpu_temperature_sysfs() == 55.0


def test_zones_sorted_numerically(sysfs):
    """thermal_zone10 does not sort before thermal_zone2."""
    _zone(sysfs, 10, "unknown-a", 70000)
    _zone(sysfs, 2, "unknown-b", 40000)
    zone = find_cpu_thermal_zone()
    assert zone is not None
    assert zone.name == "thermal_zone2"


def test_unknown_zone_type_falls_back_to_first_valid_zone(sysfs):
    """Unfamiliar boards still report the first zone, as before."""
    _zone(sysfs, 0, "broken", "not-a-number")
    _zone(sysfs, 1, "mystery-sensor", 41000)
    assert read_cpu_temperature_sysfs() == 41.0


def test_out_of_range_readings_are_ignored(sysfs):
    """A cpu zone reporting nonsense is skipped in favour of a sane one."""
    _zone(sysfs, 0, "cpu-thermal", -273000)
    _zone(sysfs, 1, "soc_thermal", 45000)
    assert read_cpu_temperature_sysfs() == 45.0


@pytest.mark.usefixtures("sysfs")
def test_no_thermal_zones():
    """Containers/VMs without /sys/class/thermal return None."""
    assert read_cpu_temperature_sysfs() is None


# ---------------------------------------------------------------------------
# hwmon temperature
# ---------------------------------------------------------------------------


def test_hwmon_coretemp_package(sysfs):
    """Intel coretemp: the 'Package id 0' sensor is used, not a single core."""
    _hwmon(
        sysfs,
        0,
        "coretemp",
        {
            "temp2_input": "51000",
            "temp2_label": "Core 0",
            "temp1_input": "58000",
            "temp1_label": "Package id 0",
        },
    )
    assert read_cpu_temperature_hwmon() == 58.0


def test_hwmon_k10temp_without_labels(sysfs):
    """AMD k10temp with no labels uses the first valid input."""
    _hwmon(sysfs, 0, "acpitz", {"temp1_input": "30000"})
    _hwmon(sysfs, 1, "k10temp", {"temp1_input": "62125"})
    assert read_cpu_temperature_hwmon() == 62.12


def test_hwmon_ignores_non_cpu_sensors(sysfs):
    """nvme/acpitz sensors are not mistaken for the CPU."""
    _hwmon(sysfs, 0, "nvme", {"temp1_input": "35000"})
    assert read_cpu_temperature_hwmon() is None


# ---------------------------------------------------------------------------
# vcgencmd
# ---------------------------------------------------------------------------


def test_vcgencmd_temperature(fake_vcgencmd):
    """Parse vcgencmd measure_temp output is parsed."""
    mock_result = MagicMock(stdout="temp=55.3'C\n")
    with patch("subprocess.run", return_value=mock_result) as run:
        assert read_cpu_temperature_vcgencmd() == 55.3
    assert run.call_args.args[0] == [str(fake_vcgencmd), "measure_temp"]
    assert run.call_args.kwargs["timeout"] == cpu_utils.VCGENCMD_TIMEOUT


@pytest.mark.usefixtures("sysfs")
def test_vcgencmd_absent():
    """No vcgencmd binary means None, without spawning anything."""
    with patch("subprocess.run") as run:
        assert read_cpu_temperature_vcgencmd() is None
        assert read_cpu_stat_vcgencmd() is None
    run.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        subprocess.CalledProcessError(255, "vcgencmd"),
        subprocess.TimeoutExpired("vcgencmd", 5),
        PermissionError("/dev/vchiq"),
    ],
)
@pytest.mark.usefixtures("fake_vcgencmd")
def test_vcgencmd_failures_return_none(error):
    """Ubuntu without video group, hung firmware, etc. are 'unavailable'."""
    with patch("subprocess.run", side_effect=error):
        assert read_cpu_temperature_vcgencmd() is None
        assert read_cpu_stat_vcgencmd() is None


@pytest.mark.usefixtures("fake_vcgencmd")
def test_vcgencmd_garbage_output():
    """'VCHI initialization failed' style output is not parsed as a value."""
    mock_result = MagicMock(stdout="VCHI initialization failed\n")
    with patch("subprocess.run", return_value=mock_result):
        assert read_cpu_temperature_vcgencmd() is None
        assert read_cpu_stat_vcgencmd() is None


@pytest.mark.usefixtures("fake_vcgencmd")
def test_vcgencmd_throttled():
    """Parse vcgencmd get_throttled output is parsed as hex."""
    mock_result = MagicMock(stdout="throttled=0x50000\n")
    with patch("subprocess.run", return_value=mock_result):
        assert read_cpu_stat_vcgencmd() == 0x50000


# ---------------------------------------------------------------------------
# read_cpu_temperature (unified)
# ---------------------------------------------------------------------------


def test_temperature_falls_back_to_hwmon(sysfs):
    """No CPU thermal zone, but a coretemp sensor."""
    _hwmon(sysfs, 0, "coretemp", {"temp1_input": "47000"})
    assert read_cpu_temperature() == 47.0


@pytest.mark.usefixtures("fake_vcgencmd")
def test_temperature_falls_back_to_vcgencmd():
    """Only vcgencmd is available."""
    with patch("subprocess.run", return_value=MagicMock(stdout="temp=60.0'C\n")):
        assert read_cpu_temperature() == 60.0


@pytest.mark.usefixtures("sysfs")
def test_temperature_none_when_nothing_available():
    """Nothing readable gives None rather than an exception."""
    assert read_cpu_temperature() is None


# ---------------------------------------------------------------------------
# Throttling
# ---------------------------------------------------------------------------


def test_firmware_sysfs_throttled(sysfs):
    """The firmware get_throttled attribute is parsed as hex."""
    _write(sysfs / "firmware" / "get_throttled", "50005")
    assert read_cpu_stat_sysfs() == 0x50005


@pytest.mark.usefixtures("sysfs")
def test_firmware_sysfs_absent():
    """No firmware attribute gives None."""
    assert read_cpu_stat_sysfs() is None


def test_rpi_volt_under_voltage(sysfs):
    """The upstream rpi_volt hwmon alarm is read."""
    _hwmon(sysfs, 0, "cpu_thermal", {"temp1_input": "40000"})
    _hwmon(sysfs, 1, "rpi_volt", {"in0_lcrit_alarm": "1"})
    assert read_under_voltage_hwmon() is True


@pytest.mark.usefixtures("sysfs")
def test_rpi_volt_absent():
    """Non-Pi hardware has no rpi_volt device."""
    assert read_under_voltage_hwmon() is None


def test_inferred_hassos_pi_under_voltage(sysfs):
    """HassOS add-on on a Pi: no vcgencmd, but rpi_volt and thermal exist."""
    _zone(sysfs, 0, "cpu-thermal", 50000, [("passive", 85000)])
    _hwmon(sysfs, 1, "rpi_volt", {"in0_lcrit_alarm": "1"})
    _cpufreq(sysfs, 1800000, 1800000)
    assert read_cpu_stat() == 1 << UNDER_VOLTAGE_BIT
    assert decode_cpu_stat_text(1 << UNDER_VOLTAGE_BIT) == "Under-voltage NOW"


def test_inferred_freq_capped(sysfs):
    """scaling_max more than 5% below cpuinfo_max sets the cap bit."""
    _cpufreq(sysfs, 900000, 1000000)
    result = read_cpu_stat_inferred()
    assert result == 1 << FREQ_CAPPED_BIT


def test_inferred_uses_passive_trip_point(sysfs):
    """The passive trip point is used, not a lower 'active' fan trip point."""
    _zone(
        sysfs,
        0,
        "cpu-thermal",
        70000,
        [("active", 60000), ("passive", 85000)],
    )
    assert read_cpu_stat_inferred() == 0

    _zone(
        sysfs,
        0,
        "cpu-thermal",
        86000,
        [("active", 60000), ("passive", 85000)],
    )
    assert read_cpu_stat_inferred() == 1 << SOFT_TEMP_LIMIT_BIT


def test_inferred_falls_back_to_trip_point_0(sysfs):
    """Without a passive trip point, trip point 0 is used as before."""
    _zone(sysfs, 0, "cpu-thermal", 80000, [("critical", 80000)])
    assert read_cpu_stat_inferred() == 1 << SOFT_TEMP_LIMIT_BIT


def test_inferred_ubuntu_x86_ok(sysfs):
    """Ubuntu x86 with cpufreq and a pkg zone but no Pi interfaces reports OK."""
    _zone(sysfs, 0, "acpitz", 27800)
    _zone(sysfs, 1, "x86_pkg_temp", 45000, [("passive", 0)])
    _cpufreq(sysfs, 4200000, 4200000)
    assert read_cpu_stat() == 0


@pytest.mark.usefixtures("sysfs")
def test_inferred_none_when_nothing_available():
    """A VM/container with no sensors at all returns None."""
    assert read_cpu_stat_inferred() is None
    assert read_cpu_stat() is None


def test_read_cpu_stat_prefers_firmware(sysfs):
    """The firmware value (with history bits) wins over the inferred one."""
    _write(sysfs / "firmware" / "get_throttled", "0x50000")
    _hwmon(sysfs, 0, "rpi_volt", {"in0_lcrit_alarm": "1"})
    assert read_cpu_stat() == 0x50000


def test_read_cpu_stat_prefers_vcgencmd_over_inferred(fake_vcgencmd):
    """Vcgencmd is used before inferring."""
    _cpufreq(fake_vcgencmd.parent.parent, 900000, 1000000)
    with patch("subprocess.run", return_value=MagicMock(stdout="throttled=0x0\n")):
        assert read_cpu_stat() == 0


# ---------------------------------------------------------------------------
# decode_cpu_stat_text
# ---------------------------------------------------------------------------


def test_decode_cpu_stat_text_zero_is_ok():
    """A bitmask of 0 decodes to 'OK'."""
    assert decode_cpu_stat_text(0) == "OK"


def test_decode_cpu_stat_text_all_current_bits():
    """All current bits set produce all NOW messages."""
    result = decode_cpu_stat_text(0b1111)
    assert "Under-voltage NOW" in result
    assert "Frequency capped NOW" in result
    assert "Throttled NOW" in result
    assert "Soft temp limit NOW" in result


def test_decode_cpu_stat_text_historical_bits():
    """Historical bits (offset +16) decode to OCCURRED messages."""
    result = decode_cpu_stat_text((1 << 16) | (1 << 18))
    assert "Under-voltage OCCURRED" in result
    assert "Throttling OCCURRED" in result
