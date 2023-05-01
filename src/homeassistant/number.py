from .common import Base


class Number(Base):
    command_topic: str | None
    command_template: str | None
    min: float | None
    max: float | None
    mode: str | None
    optimistic: bool | None
    unit_of_measurement: str | None

    def __init__(
        self,
        state_topic: str | None = None,
        command_topic: str | None = None,
        command_template: str | None = None,
        min: float | None = None,
        max: float | None = None,
        mode: str | None = None,
        step: float | None = None,
        optimistic: bool | None = None,
        unit_of_measurement: str | None = None,
        **kwargs
    ):
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
