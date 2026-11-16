"""INA219 current and voltage monitor, read over I2C with smbus2.

The Red Reactor measures the battery with a TI INA219. This driver only does
what redreactor needs: set the chip up, and read the bus voltage, the current
and the power. It follows the INA219 datasheet's calibration (section 8.5),
and works the same way as pi-ina219, which redreactor used before, so the
readings are unchanged:

- the current LSB is the expected maximum current / 32800 (a little above the
  datasheet's 32767, so an overflow can always be detected), but no smaller
  than the chip's finest step
- the power LSB is 20 x the current LSB
- with automatic gain, a current overflow raises the gain one step and tries
  again, until the highest gain still overflows

pi-ina219 needed Adafruit-GPIO, which pulls in spidev (compiled from source)
and mock. smbus2 is pure Python.
"""

from __future__ import annotations

import time
from math import trunc
from typing import Any, Protocol

DEFAULT_ADDRESS = 0x40

REGISTER_CONFIGURATION = 0x00
REGISTER_SHUNT_VOLTAGE = 0x01
REGISTER_BUS_VOLTAGE = 0x02
REGISTER_POWER = 0x03
REGISTER_CURRENT = 0x04
REGISTER_CALIBRATION = 0x05

# Configuration register bit positions
_BUS_RANGE_BIT = 13
_GAIN_BIT = 11
_BUS_ADC_BIT = 7
_SHUNT_ADC_BIT = 3
_GAIN_MASK = 0b11 << _GAIN_BIT
# Mode 7: shunt and bus voltage, continuous
_MODE_CONTINUOUS = 0b111

# Bus voltage register flags
_OVERFLOW_FLAG = 0b001

BUS_VOLTAGE_LSB = 4  # Millivolts per bit, after the 3 flag bits are removed
SHUNT_VOLTAGE_LSB = 0.01  # Millivolts per bit
CALIBRATION_FACTOR = 0.04096
CALIBRATION_MAXIMUM = 0xFFFE
CURRENT_LSB_FACTOR = 32800
# After a gain change, the next conversion needs about a millisecond
GAIN_CHANGE_DELAY = 0.001

BUS_RANGES = (16, 32)  # Volts
GAIN_VOLTS = (0.04, 0.08, 0.16, 0.32)  # Largest shunt voltage of each gain


class DeviceRangeError(Exception):
    """The current is too large to measure at the current (or any) gain."""

    def __init__(self, gain_volts: float, device_max: bool = False) -> None:
        """Record the gain the overflow happened at."""
        message = f"Current out of range (overflow), for gain {gain_volts:.2f}V"
        if device_max:
            message += ", device limit reached"
        super().__init__(message)
        self.gain_volts = gain_volts
        self.device_limit_reached = device_max


class I2CBus(Protocol):
    """The part of smbus2.SMBus this driver uses."""

    def read_i2c_block_data(
        self,
        i2c_addr: int,
        register: int,
        length: int,
    ) -> list[int]:
        """Read bytes from a register."""

    def write_i2c_block_data(
        self,
        i2c_addr: int,
        register: int,
        data: list[int],
    ) -> None:
        """Write bytes to a register."""


def _open_bus(busnum: int) -> I2CBus:
    """Open /dev/i2c-<busnum>. Imported here so tests don't need smbus2."""
    from smbus2 import SMBus  # noqa: PLC0415

    bus: I2CBus = SMBus(busnum)
    return bus


class INA219:
    """TI INA219 on an I2C bus."""

    RANGE_16V = 0
    RANGE_32V = 1
    GAIN_AUTO = -1

    # ADC settings: 9 to 12 bit single samples, or 2 to 128 averaged samples
    ADC_9BIT = 0
    ADC_10BIT = 1
    ADC_11BIT = 2
    ADC_12BIT = 3
    ADC_2SAMP = 9
    ADC_4SAMP = 10
    ADC_8SAMP = 11
    ADC_16SAMP = 12
    ADC_32SAMP = 13
    ADC_64SAMP = 14
    ADC_128SAMP = 15

    def __init__(  # noqa: PLR0913
        self,
        shunt_ohms: float,
        max_expected_amps: float | None = None,
        busnum: int = 1,
        address: int = DEFAULT_ADDRESS,
        log_level: Any = None,  # noqa: ARG002 Kept for pi-ina219's signature
        *,
        bus: I2CBus | None = None,
    ) -> None:
        """Open the I2C bus. `bus` replaces it, for tests."""
        self._bus = bus if bus is not None else _open_bus(busnum)
        self._address = address
        self._shunt_ohms = shunt_ohms
        self._max_expected_amps = max_expected_amps
        self._minimum_current_lsb = CALIBRATION_FACTOR / (
            shunt_ohms * CALIBRATION_MAXIMUM
        )
        self._voltage_range = self.RANGE_32V
        self._gain = len(GAIN_VOLTS) - 1
        self._auto_gain = False
        self._current_lsb = 0.0
        self._power_lsb = 0.0

    def configure(
        self,
        voltage_range: int = RANGE_32V,
        gain: int = GAIN_AUTO,
        bus_adc: int = ADC_12BIT,
        shunt_adc: int = ADC_12BIT,
    ) -> None:
        """Calibrate the chip and start continuous readings."""
        if voltage_range not in {self.RANGE_16V, self.RANGE_32V}:
            msg = "Invalid voltage range, must be RANGE_16V or RANGE_32V"
            raise ValueError(msg)
        self._voltage_range = voltage_range

        self._auto_gain = gain == self.GAIN_AUTO
        if not self._auto_gain:
            self._gain = gain
        elif self._max_expected_amps is not None:
            self._gain = self._gain_for(self._max_expected_amps)
        else:
            self._gain = 0

        self._calibrate(GAIN_VOLTS[self._gain], self._max_expected_amps)
        self._write(
            REGISTER_CONFIGURATION,
            voltage_range << _BUS_RANGE_BIT
            | self._gain << _GAIN_BIT
            | bus_adc << _BUS_ADC_BIT
            | shunt_adc << _SHUNT_ADC_BIT
            | _MODE_CONTINUOUS,
        )

    def voltage(self) -> float:
        """Return the bus (battery side) voltage in volts."""
        return (self._read(REGISTER_BUS_VOLTAGE) >> 3) * BUS_VOLTAGE_LSB / 1000

    def current(self) -> float:
        """Return the current in milliamps, raises DeviceRangeError on overflow."""
        self._handle_overflow()
        return self._read(REGISTER_CURRENT, signed=True) * self._current_lsb * 1000

    def power(self) -> float:
        """Return the power in milliwatts, raises DeviceRangeError on overflow."""
        self._handle_overflow()
        return self._read(REGISTER_POWER) * self._power_lsb * 1000

    def shunt_voltage(self) -> float:
        """Return the shunt voltage in millivolts."""
        self._handle_overflow()
        return self._read(REGISTER_SHUNT_VOLTAGE, signed=True) * SHUNT_VOLTAGE_LSB

    def current_overflow(self) -> bool:
        """Return whether the last conversion overflowed."""
        return bool(self._read(REGISTER_BUS_VOLTAGE) & _OVERFLOW_FLAG)

    def _gain_for(self, max_expected_amps: float) -> int:
        """Return the lowest gain whose range is above the expected current."""
        shunt_volts = max_expected_amps * self._shunt_ohms
        if shunt_volts > GAIN_VOLTS[-1]:
            msg = (
                f"Expected amps {max_expected_amps:.2f}A, out of range, use a "
                "lower value shunt resistor"
            )
            raise ValueError(msg)
        return next(i for i, volts in enumerate(GAIN_VOLTS) if volts > shunt_volts)

    def _calibrate(
        self,
        shunt_volts_max: float,
        max_expected_amps: float | None = None,
    ) -> None:
        """Work out the current and power steps, and write the calibration."""
        max_possible_amps = shunt_volts_max / self._shunt_ohms
        if max_expected_amps is not None:
            if max_expected_amps > round(max_possible_amps, 3):
                msg = (
                    f"Expected current {max_expected_amps:.3f}A is greater than "
                    f"max possible current {max_possible_amps:.3f}A"
                )
                raise ValueError(msg)
            current_lsb = min(max_expected_amps, max_possible_amps) / (
                CURRENT_LSB_FACTOR
            )
        else:
            current_lsb = max_possible_amps / CURRENT_LSB_FACTOR

        self._current_lsb = max(current_lsb, self._minimum_current_lsb)
        self._power_lsb = self._current_lsb * 20
        self._write(
            REGISTER_CALIBRATION,
            trunc(CALIBRATION_FACTOR / (self._current_lsb * self._shunt_ohms)),
        )

    def _handle_overflow(self) -> None:
        """Raise the gain while the current overflows, or raise an error."""
        while self.current_overflow():
            if not self._auto_gain:
                raise DeviceRangeError(GAIN_VOLTS[self._gain])
            if self._gain >= len(GAIN_VOLTS) - 1:
                raise DeviceRangeError(GAIN_VOLTS[self._gain], device_max=True)
            self._gain += 1
            self._calibrate(GAIN_VOLTS[self._gain])
            configuration = self._read(REGISTER_CONFIGURATION) & ~_GAIN_MASK
            self._write(
                REGISTER_CONFIGURATION,
                (configuration & 0xFFFF) | self._gain << _GAIN_BIT,
            )
            time.sleep(GAIN_CHANGE_DELAY)

    def _read(self, register: int, signed: bool = False) -> int:
        """Read a 16 bit register, most significant byte first."""
        high, low = self._bus.read_i2c_block_data(self._address, register, 2)
        value = high << 8 | low
        if signed and value & 0x8000:
            value -= 0x10000
        return value

    def _write(self, register: int, value: int) -> None:
        """Write a 16 bit register, most significant byte first."""
        self._bus.write_i2c_block_data(
            self._address,
            register,
            [(value >> 8) & 0xFF, value & 0xFF],
        )
