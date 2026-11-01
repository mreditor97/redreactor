"""Home Assistant Event."""

from __future__ import annotations

from typing import Any

from .common import Base


class Event(Base):
    """Home Assistant Event."""

    event_types: list[str] | None

    def __init__(
        self,
        event_types: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialise Home Assistant Event."""
        super().__init__(**kwargs)
        self.event_types = event_types
