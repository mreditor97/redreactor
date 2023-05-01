from .common import Base


class Button(Base):
    command_topic: str | None
    command_template: str | None
    payload_press: str | None

    def __init__(
        self,
        command_topic: str | None = None,
        command_template: str | None = None,
        payload_press: str | None = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.command_topic = command_topic
        self.command_template = command_template
        self.payload_press = payload_press
