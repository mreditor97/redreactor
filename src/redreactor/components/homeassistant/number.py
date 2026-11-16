"""Home Assistant Number."""

from __future__ import annotations

from dataclasses import dataclass

from .common import Base


@dataclass(kw_only=True, repr=False)
class Number(Base):
    """Home Assistant Number."""

    command_topic: str | None = None
    command_template: str | None = None
    min: float | None = None
    max: float | None = None
    mode: str | None = None
    step: float | None = None
    optimistic: bool | None = None
    unit_of_measurement: str | None = None
