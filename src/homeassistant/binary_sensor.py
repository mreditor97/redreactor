from .common import Base


class BinarySensor(Base):
    payload_on: str | None
    payload_off: str | None

    def __init__(
        self, payload_on: str | None = None, payload_off: str | None = None, **kwargs
    ):
        super().__init__(**kwargs)
        self.payload_on = payload_on
        self.payload_off = payload_off
