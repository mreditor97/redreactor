"""Home Assistant Binary Sensor."""

from __future__ import annotations

from dataclasses import dataclass

from .common import Base


@dataclass(kw_only=True, repr=False)
class BinarySensor(Base):
    """Home Assistant Binary Sensor."""

    payload_on: str | None = None
    payload_off: str | None = None
