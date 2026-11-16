"""Tests for the battery level and time remaining maths."""

from __future__ import annotations

import logging

import pytest

from redreactor.helpers import battery

CURVE = [[3.0, 0.0], [3.6, 50.0], [4.2, 100.0]]


def test_reading_average_keeps_the_last_readings():
    """Only the last `size` readings are averaged."""
    average = battery.ReadingAverage(2)

    assert average.add(3.0, 100.0) == (3.0, 100.0)
    assert average.add(4.0, 200.0) == (3.5, 150.0)
    assert average.add(4.0, 300.0) == (4.0, 250.0)
    assert len(average) == 2


def test_reading_average_of_one_is_off():
    """A size of 1, or less, uses each reading as it is."""
    average = battery.ReadingAverage(0)

    average.add(3.0, 100.0)
    assert average.add(4.0, 200.0) == (4.0, 200.0)


def test_resting_voltage_adds_back_the_sag():
    """500 mA through 100 milliohms sags the voltage by 0.05 V."""
    assert battery.resting_voltage(3.7, 500.0, 100.0) == pytest.approx(3.75)
    # Charging current is negative, so the rise is taken off
    assert battery.resting_voltage(3.7, -500.0, 100.0) == pytest.approx(3.65)
    assert battery.resting_voltage(3.7, 500.0, 0.0) == 3.7


@pytest.mark.parametrize(
    ("voltage", "level"),
    [(2.5, 0.0), (3.0, 0.0), (3.3, 25.0), (3.6, 50.0), (3.9, 75.0), (4.5, 100.0)],
)
def test_interpolate_curve(voltage, level):
    """Levels are interpolated between the points and clamped to the ends."""
    assert battery.interpolate_curve(CURVE, voltage) == pytest.approx(level)


def test_linear_level_is_clamped():
    """The straight line level stays within 0 to 100."""
    assert battery.linear_level(2.0, 2.9, 4.2) == 0
    assert battery.linear_level(5.0, 2.9, 4.2) == 100
    # 0.7 V of the 1.27 V range, after the 0.03 V taken off the maximum
    assert battery.linear_level(3.6, 2.9, 4.2) == 55


def test_linear_level_inverted_range_uses_the_defaults(caplog):
    """A minimum that isn't below the maximum falls back to the defaults."""
    with caplog.at_level(logging.ERROR, logger="Red Reactor"):
        level = battery.linear_level(2.8, 4.0, 3.0)

    assert level == 0
    assert "is not below maximum" in caplog.text


def test_battery_level_uses_the_curve_when_set():
    """The curve is used when there is one, the straight line otherwise."""
    common = {"internal_resistance": 0.0, "minimum": 2.9, "maximum": 4.2}

    assert battery.battery_level(3.6, 0.0, curve=CURVE, **common) == 50
    assert battery.battery_level(3.6, 0.0, curve=None, **common) == 55


def test_time_remaining():
    """3000 mAh at 50% above a 10% shutdown level, drawing 500 mA."""
    days = battery.time_remaining(
        capacity=3000,
        level=60,
        shutdown_level=10,
        current=500.0,
        external_power=False,
    )

    assert days == pytest.approx(1500 / 500 / 24, abs=0.001)


@pytest.mark.parametrize(
    ("capacity", "current", "external_power"),
    [(0, 500.0, False), (3000, 500.0, True), (3000, -100.0, False)],
)
def test_time_remaining_unknown(capacity, current, external_power):
    """Unknown without a capacity, or while the battery isn't discharging."""
    assert (
        battery.time_remaining(
            capacity=capacity,
            level=60,
            shutdown_level=10,
            current=current,
            external_power=external_power,
        )
        is None
    )
