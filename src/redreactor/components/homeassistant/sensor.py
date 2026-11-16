"""Home Assistant Sensor."""

from __future__ import annotations

from dataclasses import dataclass

from .common import Base


@dataclass(kw_only=True, repr=False)
class Sensor(Base):
    """Home Assistant Sensor."""

    unit_of_measurement: str | None = None
    suggested_display_precision: int | None = None
    state_class: str | None = None
