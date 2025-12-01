"""Home Assistant Sensor."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .common import Base

if TYPE_CHECKING:
    import datetime
    import decimal


class Sensor(Base):
    """Home Assistant Sensor."""

    unit_of_measurement: str | None
    suggested_display_precision: int | None
    state_class: str | None
    native_value: (
        str | int | float | datetime.date | datetime.datetime | decimal.Decimal | None
    )  # noqa: E501

    def __init__(
        self,
        unit_of_measurement: str | None = None,
        suggested_display_precision: int | None = None,
        state_class: str | None = None,
        native_value: (
            str | float | datetime.date | datetime.datetime | decimal.Decimal | None
        ) = None,  # noqa: E501
        **kwargs: Any,
    ) -> None:
        """Initialise Home Assistant sensor."""
        super().__init__(**kwargs)
        self.unit_of_measurement = unit_of_measurement
        self.suggested_display_precision = suggested_display_precision
        self.state_class = state_class
        self.native_value = native_value
