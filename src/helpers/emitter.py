"""Event Emitter.

Custom event emitter.
"""
from typing import Any


class EventEmitter:
    """Event Emitter module.

    Allows the creation of callback style functionality.
    """

    def __init__(self) -> None:
        """Initialise Event Emitter."""
        self.__callbacks: dict[str, callable] = {}

    def on(self, event_name: str, function: Any) -> None:
        """Register event."""
        self.__callbacks[event_name] = [*self.__callbacks.get(event_name, []), function]
        return function

    def emit(self, event_name: str, *args: tuple, **kwargs: dict[str, Any]) -> Any:
        """Event trigger."""
        [function(*args, **kwargs) for function in self.__callbacks.get(event_name, [])]

    def off(self, event_name: str, function: Any) -> None:
        """Event stop."""
        self.__callbacks.get(event_name, []).remove(function)
