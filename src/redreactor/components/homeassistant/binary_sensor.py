"""Home Assistant Binary Sensor."""

from typing import Any

from .common import Base


class BinarySensor(Base):
    """Home Assistant Binary Sensor."""

    payload_on: str | None
    payload_off: str | None

    def __init__(
        self,
        payload_on: str | None = None,
        payload_off: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialise Home Assistant Binary Sensor."""
        super().__init__(**kwargs)
        self.payload_on = payload_on
        self.payload_off = payload_off
