"""Home Assistant Event."""

from __future__ import annotations

from dataclasses import dataclass

from .common import Base


@dataclass(kw_only=True, repr=False)
class Event(Base):
    """Home Assistant Event."""

    event_types: list[str] | None = None
