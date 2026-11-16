"""Battery level and time remaining, worked out from the INA219 readings.

These only do the maths, so they can be tested without a monitor. The monitor
passes in the settings in use.
"""

from __future__ import annotations

import logging
from collections import deque
from itertools import pairwise

from redreactor.const import (
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
    DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP,
    DEFAULT_BATTERY_VOLTAGE_MINIMUM,
    HOURS_PER_DAY,
)

logger = logging.getLogger("Red Reactor")


class ReadingAverage:
    """The average of the last few (voltage, current) readings.

    Brief current spikes make single voltage readings jump, so the battery
    level is worked out from an average. The load correction is linear, so
    averaging the voltage and current first gives the same result as averaging
    corrected voltages.
    """

    def __init__(self, size: int) -> None:
        """Keep up to `size` readings, 1 turns the averaging off."""
        self._readings: deque[tuple[float, float]] = deque(maxlen=max(size, 1))

    def add(self, voltage: float, current: float) -> tuple[float, float]:
        """Add a reading, and return the average voltage and current."""
        self._readings.append((voltage, current))
        count = len(self._readings)
        return (
            sum(reading[0] for reading in self._readings) / count,
            sum(reading[1] for reading in self._readings) / count,
        )

    def __len__(self) -> int:
        """Return the number of readings held."""
        return len(self._readings)


def resting_voltage(
    voltage: float,
    current: float,
    internal_resistance: float,
) -> float:
    """Estimate the battery's voltage without the load.

    The voltage sags under load by roughly current x internal resistance
    (milliamps and milliohms), so that is added back. Charging current is
    negative, so the rise while charging is taken off. A resistance of 0
    leaves the voltage as measured.
    """
    return voltage + current / 1000 * internal_resistance / 1000


def interpolate_curve(curve: list[list[float]], voltage: float) -> float:
    """Interpolate the battery level between the points of the curve.

    The curve is checked at start up to have rising voltages, so it can be
    walked in order. Voltages outside it are clamped to its ends.
    """
    if voltage <= curve[0][0]:
        return curve[0][1]

    for lower, upper in pairwise(curve):
        lower_voltage, lower_level = lower
        upper_voltage, upper_level = upper
        if voltage <= upper_voltage:
            return lower_level + (voltage - lower_voltage) / (
                upper_voltage - lower_voltage
            ) * (upper_level - lower_level)

    return curve[-1][1]


def linear_level(voltage: float, minimum: float, maximum: float) -> int:
    """Return the battery level on a straight line between two voltages.

    Subtracting DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP from the ceiling stops
    the level reaching 100% while the battery is still under load (the voltage
    sags a little even when fully charged). The result is clamped to 0 to 100,
    so readings out of range are safe.

    If the minimum is not below the maximum the scale would be inverted and
    the level could never reach 0%, so low battery shutdown would never
    happen. In that case the default voltages are used instead.
    """
    if maximum - DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP <= minimum:
        logger.error(
            "Battery voltage minimum %fV is not below maximum %fV, "
            "using the default %fV to %fV instead",
            minimum,
            maximum,
            DEFAULT_BATTERY_VOLTAGE_MINIMUM,
            DEFAULT_BATTERY_VOLTAGE_MAXIMUM,
        )
        minimum = DEFAULT_BATTERY_VOLTAGE_MINIMUM
        maximum = DEFAULT_BATTERY_VOLTAGE_MAXIMUM

    level = (
        (voltage - minimum)
        / (maximum - DEFAULT_BATTERY_VOLTAGE_MAXIMUM_DROP - minimum)
        * 100
    )
    return int(max(min(100, level), 0))


def battery_level(  # noqa: PLR0913
    voltage: float,
    current: float,
    *,
    internal_resistance: float,
    curve: list[list[float]] | None,
    minimum: float,
    maximum: float,
) -> int:
    """Return the battery level (%) for a voltage and current reading.

    The voltage is first corrected for the load. It is then turned into a
    level with `curve` when there is one, as a Li-ion battery's voltage isn't
    linear with its charge, or a straight line between the minimum and
    maximum voltage otherwise.
    """
    resting = resting_voltage(voltage, current, internal_resistance)
    if curve:
        return round(interpolate_curve(curve, resting))
    return linear_level(resting, minimum, maximum)


def time_remaining(  # noqa: PLR0913
    *,
    capacity: float,
    level: float,
    shutdown_level: float,
    current: float,
    external_power: bool,
) -> float | None:
    """Estimate the days left on battery before the low battery shutdown.

    The charge left above the shutdown level, from the capacity (mAh) and the
    voltage based battery level, divided by the current being drawn (mA). The
    battery level isn't linear with the charge and the current changes with
    the load, so this is a rough guide only.

    Returns None (unknown in Home Assistant) when the capacity isn't set, or
    while there is external power so the battery isn't discharging.
    """
    if capacity <= 0 or external_power or current <= 0:
        return None

    usable_percentage = max(level - shutdown_level, 0)
    remaining_mah = capacity * usable_percentage / 100

    return round(remaining_mah / current / HOURS_PER_DAY, 3)
