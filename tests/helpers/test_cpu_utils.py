"""Tests for cpu_utils."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from redreactor.helpers.cpu_utils import (
    decode_cpu_stat_text,
    read_cpu_stat_hassos,
    read_cpu_stat_inferred,
    read_cpu_stat_sysfs,
    read_cpu_stat_vcgencmd,
    read_cpu_temperature,
    read_cpu_temperature_sysfs,
    read_cpu_temperature_vcgencmd,
)

# ---------------------------------------------------------------------------
# read_cpu_temperature_sysfs
# ---------------------------------------------------------------------------


def test_read_cpu_temperature_sysfs_returns_value(tmp_path):
    """read_cpu_temperature_sysfs returns millidegrees / 1000 when file exists."""
    temp_file = tmp_path / "temp"
    temp_file.write_text("42000")

    with patch("redreactor.helpers.cpu_utils.SYSFS_TEMP_PATHS", [temp_file]):
        result = read_cpu_temperature_sysfs()

    assert result == 42.0


def test_read_cpu_temperature_sysfs_returns_none_when_absent():
    """read_cpu_temperature_sysfs returns None when no sysfs path exists."""
    fake_path = Path("/nonexistent/thermal_zone0/temp")
    with patch("redreactor.helpers.cpu_utils.SYSFS_TEMP_PATHS", [fake_path]):
        result = read_cpu_temperature_sysfs()
    assert result is None


# ---------------------------------------------------------------------------
# read_cpu_temperature_vcgencmd
# ---------------------------------------------------------------------------


def test_read_cpu_temperature_vcgencmd_returns_value(tmp_path):
    """read_cpu_temperature_vcgencmd parses output correctly."""
    fake_bin = tmp_path / "vcgencmd"
    fake_bin.write_text("#!/bin/sh\necho 'temp=55.3'C'")
    fake_bin.chmod(0o755)

    mock_result = MagicMock()
    mock_result.stdout = "temp=55.3'C\n"

    with patch("redreactor.helpers.cpu_utils.Path.exists", return_value=True), \
         patch("subprocess.run", return_value=mock_result):
        result = read_cpu_temperature_vcgencmd()

    assert result == 55.3


def test_read_cpu_temperature_vcgencmd_returns_none_when_absent():
    """read_cpu_temperature_vcgencmd returns None when vcgencmd not found."""
    with patch("redreactor.helpers.cpu_utils.Path.exists", return_value=False):
        result = read_cpu_temperature_vcgencmd()
    assert result is None


# ---------------------------------------------------------------------------
# read_cpu_temperature (unified)
# ---------------------------------------------------------------------------


def test_read_cpu_temperature_uses_sysfs_when_available():
    """read_cpu_temperature returns sysfs value when sysfs is available."""
    with patch(
        "redreactor.helpers.cpu_utils.read_cpu_temperature_sysfs", return_value=50.0,
    ):
        result = read_cpu_temperature()
    assert result == 50.0


def test_read_cpu_temperature_falls_back_to_vcgencmd():
    """read_cpu_temperature falls back to vcgencmd when sysfs returns None."""
    with patch(
        "redreactor.helpers.cpu_utils.read_cpu_temperature_sysfs", return_value=None,
    ), patch(
        "redreactor.helpers.cpu_utils.read_cpu_temperature_vcgencmd", return_value=55.3,
    ):
        result = read_cpu_temperature()
    assert result == 55.3


# ---------------------------------------------------------------------------
# read_cpu_stat_sysfs
# ---------------------------------------------------------------------------


def test_read_cpu_stat_sysfs_returns_value(tmp_path):
    """read_cpu_stat_sysfs parses hex string from sysfs path."""
    throttle_file = tmp_path / "get_throttled"
    throttle_file.write_text("0x50000\n")

    with patch("redreactor.helpers.cpu_utils.SYSFS_THROTTLE_PATHS", [throttle_file]):
        result = read_cpu_stat_sysfs()

    assert result == 0x50000


def test_read_cpu_stat_sysfs_returns_none_when_absent():
    """read_cpu_stat_sysfs returns None when no sysfs path exists."""
    fake_path = Path("/nonexistent/get_throttled")
    with patch("redreactor.helpers.cpu_utils.SYSFS_THROTTLE_PATHS", [fake_path]):
        result = read_cpu_stat_sysfs()
    assert result is None


# ---------------------------------------------------------------------------
# read_cpu_stat_vcgencmd
# ---------------------------------------------------------------------------


def test_read_cpu_stat_vcgencmd_returns_value():
    """read_cpu_stat_vcgencmd parses hex throttle value from vcgencmd output."""
    mock_result = MagicMock()
    mock_result.stdout = "throttled=0x50000\n"

    with patch("redreactor.helpers.cpu_utils.Path.exists", return_value=True), \
         patch("subprocess.run", return_value=mock_result):
        result = read_cpu_stat_vcgencmd()

    assert result == 0x50000


def test_read_cpu_stat_vcgencmd_returns_none_when_absent():
    """read_cpu_stat_vcgencmd returns None when vcgencmd is not present."""
    with patch("redreactor.helpers.cpu_utils.Path.exists", return_value=False):
        result = read_cpu_stat_vcgencmd()
    assert result is None


# ---------------------------------------------------------------------------
# read_cpu_stat_hassos
# ---------------------------------------------------------------------------


def test_read_cpu_stat_hassos_returns_none_without_token(monkeypatch):
    """read_cpu_stat_hassos returns None when SUPERVISOR_TOKEN is not set."""
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    result = read_cpu_stat_hassos()
    assert result is None


def test_read_cpu_stat_hassos_parses_throttling(monkeypatch):
    """read_cpu_stat_hassos builds a bitmask from throttling JSON."""
    monkeypatch.setenv("SUPERVISOR_TOKEN", "fake-token")

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": {
            "chassis": {
                "throttling": {
                    "under_voltage": True,
                    "frequency_capped": False,
                    "throttled": False,
                    "soft_temp_limit": False,
                },
            },
        },
    }

    with patch("requests.get", return_value=mock_response):
        result = read_cpu_stat_hassos()

    assert result == 0b0001  # under_voltage bit only


def test_read_cpu_stat_hassos_returns_none_on_missing_key(monkeypatch):
    """read_cpu_stat_hassos returns None when throttling key is absent."""
    monkeypatch.setenv("SUPERVISOR_TOKEN", "fake-token")

    mock_response = MagicMock()
    mock_response.json.return_value = {"data": {}}

    with patch("requests.get", return_value=mock_response):
        result = read_cpu_stat_hassos()

    assert result is None


# ---------------------------------------------------------------------------
# read_cpu_stat_inferred
# ---------------------------------------------------------------------------


def test_read_cpu_stat_inferred_freq_capped_bit():
    """read_cpu_stat_inferred sets freq_capped bit when scaling_max is low."""
    with patch(
        "redreactor.helpers.cpu_utils._read_int",
        side_effect=lambda p: {
            "scaling_cur_freq": 1000000,
            "scaling_max_freq": 900000,   # < 0.95 * 1000000
            "cpuinfo_max_freq": 1000000,
            "temp": 50000,
            "trip_point_0_temp": 80000,
        }.get(p.name),
    ):
        result = read_cpu_stat_inferred()

    assert result is not None
    assert result & (1 << 1)  # FREQ_CAPPED_BIT


def test_read_cpu_stat_inferred_soft_temp_bit():
    """read_cpu_stat_inferred sets soft_temp_limit bit when temp exceeds trip point."""
    with patch(
        "redreactor.helpers.cpu_utils._read_int",
        side_effect=lambda p: {
            "scaling_cur_freq": 1000000,
            "scaling_max_freq": 1000000,
            "cpuinfo_max_freq": 1000000,
            "temp": 80000,
            "trip_point_0_temp": 80000,  # Equal triggers soft temp
        }.get(p.name),
    ):
        result = read_cpu_stat_inferred()

    assert result is not None
    assert result & (1 << 3)  # SOFT_TEMP_LIMIT_BIT


def test_read_cpu_stat_inferred_returns_none_when_all_missing():
    """read_cpu_stat_inferred returns None when all data is unavailable."""
    with patch("redreactor.helpers.cpu_utils._read_int", return_value=None):
        result = read_cpu_stat_inferred()
    assert result is None


# ---------------------------------------------------------------------------
# decode_cpu_stat_text
# ---------------------------------------------------------------------------


def test_decode_cpu_stat_text_zero_is_ok():
    """A bitmask of 0 decodes to 'OK'."""
    assert decode_cpu_stat_text(0) == "OK"


def test_decode_cpu_stat_text_under_voltage_bit():
    """Under-voltage bit (0) decodes to 'Under-voltage NOW'."""
    result = decode_cpu_stat_text(1 << 0)
    assert "Under-voltage NOW" in result


def test_decode_cpu_stat_text_all_current_bits():
    """All current bits set produce all NOW messages."""
    mask = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3)
    result = decode_cpu_stat_text(mask)
    assert "Under-voltage NOW" in result
    assert "Frequency capped NOW" in result
    assert "Throttled NOW" in result
    assert "Soft temp limit NOW" in result


def test_decode_cpu_stat_text_historical_bits():
    """Historical bits (offset +16) decode to OCCURRED messages."""
    mask = (1 << (0 + 16)) | (1 << (2 + 16))
    result = decode_cpu_stat_text(mask)
    assert "Under-voltage OCCURRED" in result
    assert "Throttling OCCURRED" in result
