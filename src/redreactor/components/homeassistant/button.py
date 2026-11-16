"""Home Assistant Button."""

from __future__ import annotations

from dataclasses import dataclass

from .common import Base


@dataclass(kw_only=True, repr=False)
class Button(Base):
    """Home Assistant Button."""

    command_topic: str | None = None
    command_template: str | None = None
    payload_press: str | None = None
