from typing import Any


class EventEmitter:
    def __init__(self):
        self.__callbacks: dict[str, callable] = dict()

    def on(self, event_name: str, function: Any):
        self.__callbacks[event_name] = self.__callbacks.get(event_name, []) + [function]
        return function

    def emit(self, event_name: str, *args, **kwargs):
        [function(*args, **kwargs) for function in self.__callbacks.get(event_name, [])]

    def off(self, event_name: str, function: Any):
        self.__callbacks.get(event_name, []).remove(function)
