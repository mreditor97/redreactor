from .common import Base


class Sensor(Base):
    unit_of_measurement: str | None
    suggested_display_precision: int | None
    state_class: str | None

    def __init__(
        self,
        unit_of_measurement: str | None = None,
        suggested_display_precision: int | None = None,
        state_class: str | None = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.unit_of_measurement = unit_of_measurement
        self.suggested_display_precision = suggested_display_precision
        self.state_class = state_class
