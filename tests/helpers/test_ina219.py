"""Tests for the INA219 driver, against a fake I2C bus."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from redreactor.helpers.ina219 import (
    INA219,
    REGISTER_BUS_VOLTAGE,
    REGISTER_CALIBRATION,
    REGISTER_CONFIGURATION,
    REGISTER_CURRENT,
    REGISTER_POWER,
    REGISTER_SHUNT_VOLTAGE,
    DeviceRangeError,
)


class FakeBus:
    """16 bit registers of one INA219, read and written most significant first."""

    def __init__(self) -> None:  # noqa: D107
        self.registers = dict.fromkeys(range(6), 0)
        self.writes: list[tuple[int, int, int]] = []

    def read_i2c_block_data(self, _address, register, length):
        assert length == 2
        value = self.registers[register]
        return [value >> 8, value & 0xFF]

    def write_i2c_block_data(self, address, register, data):
        value = data[0] << 8 | data[1]
        self.registers[register] = value
        self.writes.append((address, register, value))


def _red_reactor(bus: FakeBus, **configure: int) -> INA219:
    """Set up the INA219 the way the Red Reactor does."""
    ina = INA219(shunt_ohms=0.05, max_expected_amps=5.5, address=0x40, bus=bus)
    ina.configure(voltage_range=ina.RANGE_16V, **configure)
    return ina


def test_configure_writes_calibration_then_configuration():
    """5.5 A on a 50 mΩ shunt: calibration 4885, 16 V range, 320 mV gain."""
    bus = FakeBus()
    _red_reactor(bus)

    assert bus.writes == [
        # trunc(0.04096 / (5.5 / 32800 * 0.05))
        (0x40, REGISTER_CALIBRATION, 4885),
        # 16 V range, gain 3, 12-bit bus and shunt ADC, continuous
        (0x40, REGISTER_CONFIGURATION, 0x199F),
    ]


def test_configure_sets_adc_averaging():
    """128 samples (15) go into both ADC fields."""
    bus = FakeBus()
    _red_reactor(bus, bus_adc=INA219.ADC_128SAMP, shunt_adc=INA219.ADC_128SAMP)

    assert bus.registers[REGISTER_CONFIGURATION] == (
        3 << 11 | 15 << 7 | 15 << 3 | 0b111
    )


def test_voltage_ignores_the_flag_bits():
    """The bus voltage is bits 3 to 15, 4 mV each."""
    bus = FakeBus()
    ina = _red_reactor(bus)
    bus.registers[REGISTER_BUS_VOLTAGE] = (1000 << 3) | 0b010  # Conversion ready

    assert ina.voltage() == pytest.approx(4.0)


def test_current_is_signed():
    """A charging current reads negative."""
    bus = FakeBus()
    ina = _red_reactor(bus)
    lsb_ma = 5.5 / 32800 * 1000

    bus.registers[REGISTER_CURRENT] = 3000
    assert ina.current() == pytest.approx(3000 * lsb_ma)

    bus.registers[REGISTER_CURRENT] = 0x10000 - 3000
    assert ina.current() == pytest.approx(-3000 * lsb_ma)


def test_power_and_shunt_voltage():
    """Power is 20 current steps per bit, the shunt 10 µV per bit."""
    bus = FakeBus()
    ina = _red_reactor(bus)
    bus.registers[REGISTER_POWER] = 100
    bus.registers[REGISTER_SHUNT_VOLTAGE] = 0x10000 - 500

    assert ina.power() == pytest.approx(100 * 20 * 5.5 / 32800 * 1000)
    assert ina.shunt_voltage() == pytest.approx(-5.0)


def test_overflow_at_the_highest_gain_raises():
    """The Red Reactor already uses the highest gain, so overflow is an error."""
    bus = FakeBus()
    ina = _red_reactor(bus)
    bus.registers[REGISTER_BUS_VOLTAGE] = 0b001

    with pytest.raises(DeviceRangeError) as error:
        ina.current()

    assert error.value.device_limit_reached is True
    assert error.value.gain_volts == pytest.approx(0.32)


def test_overflow_with_fixed_gain_raises_without_device_limit():
    """A fixed gain raises straight away rather than changing the gain."""
    bus = FakeBus()
    ina = INA219(shunt_ohms=0.05, max_expected_amps=1.0, bus=bus)
    ina.configure(gain=1)
    bus.registers[REGISTER_BUS_VOLTAGE] = 0b001

    with pytest.raises(DeviceRangeError) as error:
        ina.current()

    assert error.value.device_limit_reached is False


def test_overflow_raises_the_automatic_gain():
    """With automatic gain, an overflow steps the gain up and reads again."""
    bus = FakeBus()
    ina = INA219(shunt_ohms=0.05, max_expected_amps=1.0, bus=bus)
    ina.configure()
    # 1 A x 50 mΩ = 50 mV, so the 80 mV gain (1) is chosen
    assert (bus.registers[REGISTER_CONFIGURATION] >> 11) & 0b11 == 1

    reads = []
    original = bus.read_i2c_block_data

    def read(address, register, length):
        reads.append(register)
        if register == REGISTER_BUS_VOLTAGE and reads.count(register) == 1:
            return [0, 0b001]  # Overflow once, then fine
        return original(address, register, length)

    bus.read_i2c_block_data = read
    bus.registers[REGISTER_CURRENT] = 10
    with patch("redreactor.helpers.ina219.time.sleep"):
        ina.current()

    assert (bus.registers[REGISTER_CONFIGURATION] >> 11) & 0b11 == 2
    # Recalibrated for 160 mV without the expected current
    assert bus.registers[REGISTER_CALIBRATION] == int(
        0.04096 / ((0.16 / 0.05) / 32800 * 0.05),
    )


def test_expected_current_above_the_shunt_range_is_refused():
    """More than 320 mV across the shunt can't be measured."""
    ina = INA219(shunt_ohms=0.1, max_expected_amps=3.3, bus=FakeBus())

    with pytest.raises(ValueError, match="out of range"):
        ina.configure()


def test_invalid_voltage_range_is_refused():
    """Only the 16 V and 32 V ranges exist."""
    ina = INA219(shunt_ohms=0.05, max_expected_amps=5.5, bus=FakeBus())

    with pytest.raises(ValueError, match="voltage range"):
        ina.configure(voltage_range=2)


def test_opens_the_configured_bus():
    """Without a bus given, /dev/i2c-<busnum> is opened with smbus2."""
    with patch("smbus2.SMBus") as smbus:
        INA219(shunt_ohms=0.05, busnum=3)

    smbus.assert_called_once_with(3)


def test_missing_bus_raises_os_error():
    """A missing I2C device is an OSError, which the monitor handles."""
    with pytest.raises(OSError):  # noqa: PT011
        INA219(shunt_ohms=0.05, busnum=250)
