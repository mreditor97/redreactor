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
        self.__callbacks: Any = {}

    def on(self, event_name: str, function: Any) -> Any:
        """Register event to a specific item."""
        self.__callbacks[event_name] = [*self.__callbacks.get(event_name, []), function]
        return function

    def emit(
        self,
        event_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Event trigger."""
        for function in self.__callbacks.get(event_name, []):
            function(*args, **kwargs)

    def off(self, event_name: str, function: Any) -> None:
        """Event stop."""
        self.__callbacks.get(event_name, []).remove(function)
