"""Home Assistant Text."""

from __future__ import annotations

from typing import Any

from .common import Base


class Text(Base):
    """Home Assistant Text."""

    min: int | None
    max: int | None
    mode: str | None

    def __init__(
        self,
        min: int | None = None,  # noqa: A002
        max: int | None = None,  # noqa: A002
        mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialise Home Assistant text."""
        super().__init__(**kwargs)
        self.min = min
        self.max = max
        self.mode = mode
