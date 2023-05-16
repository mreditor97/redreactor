"""Home Assistant Number."""

from typing import Any

from .common import Base


class Number(Base):
    """Home Assistant Number."""

    command_topic: str | None
    command_template: str | None
    min: float | None  # noqa: A003
    max: float | None  # noqa: A003
    mode: str | None
    optimistic: bool | None
    unit_of_measurement: str | None

    def __init__(  # noqa: PLR0913
        self,
        state_topic: str | None = None,
        command_topic: str | None = None,
        command_template: str | None = None,
        min: float | None = None,  # noqa: A002
        max: float | None = None,  # noqa: A002
        mode: str | None = None,
        step: float | None = None,
        optimistic: bool | None = None,
        unit_of_measurement: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialise Home Assistant number."""
        super().__init__(**kwargs)
        self.state_topic = state_topic
        self.command_topic = command_topic
        self.command_template = command_template
        self.min = min
        self.max = max
        self.mode = mode
        self.step = step
        self.optimistic = optimistic
        self.unit_of_measurement = unit_of_measurement
