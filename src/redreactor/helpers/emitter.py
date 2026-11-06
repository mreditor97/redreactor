"""Event Emitter.

Custom event emitter.
"""

import logging
from typing import Any

logger = logging.getLogger("Red Reactor")


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
        # Returning the function allows this method to be used as a decorator.
        return function

    def emit(
        self,
        event_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Event trigger.

        A listener that raises is logged and the remaining listeners still run.
        Events are mostly emitted from inside paho callbacks, where an exception
        would end loop_forever() and stop the whole service. SystemExit and
        KeyboardInterrupt are not caught, so a deliberate exit still works.
        """
        for function in self.__callbacks.get(event_name, []):
            try:
                function(*args, **kwargs)
            except Exception:
                logger.exception(
                    "Error in the %s listener %s",
                    event_name,
                    getattr(function, "__qualname__", function),
                )

    def off(self, event_name: str, function: Any) -> None:
        """Event stop."""
        self.__callbacks.get(event_name, []).remove(function)
