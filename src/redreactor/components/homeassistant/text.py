"""Home Assistant Text."""

from __future__ import annotations

from typing import Any

from .common import Base


class Text(Base):
    """Home Assistant Text."""

    command_topic: str | None
    command_template: str | None
    min: int | None
    max: int | None
    mode: str | None

    def __init__(
        self,
        command_topic: str | None = None,
        command_template: str | None = None,
        min: int | None = None,  # noqa: A002
        max: int | None = None,  # noqa: A002
        mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialise Home Assistant text."""
        super().__init__(**kwargs)
        self.command_topic = command_topic
        self.command_template = command_template
        self.min = min
        self.max = max
        self.mode = mode
