"""Home Assistant Sensor."""


from typing import Any

from .common import Base


class Sensor(Base):
    """Home Assistant Sensor."""

    unit_of_measurement: str | None
    suggested_display_precision: int | None
    state_class: str | None

    def __init__(
        self,
        unit_of_measurement: str | None = None,
        suggested_display_precision: int | None = None,
        state_class: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialise Home Assistant sensor."""
        super().__init__(**kwargs)
        self.unit_of_measurement = unit_of_measurement
        self.suggested_display_precision = suggested_display_precision
        self.state_class = state_class
