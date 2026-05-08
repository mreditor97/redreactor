"""Repeat Timer module."""

from threading import Timer
from typing import Any


class RepeatTimer:
    """Repeat Timer."""

    _timer: Timer

    interval: float
    function: Any
    args: Any
    kwargs: Any
    is_running: bool

    def __init__(
        self,
        interval: float,
        function: Any,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Initialise Repeat Timer object."""
        self.interval = interval
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.is_running = False

    def _run(self) -> None:
        """Run timer."""
        # Schedule the next tick BEFORE invoking the callback so the interval
        # is measured from the start of each call, not the end.  It also means
        # a stop() issued from inside the callback will cancel the already-
        # queued next timer rather than being silently ignored.
        self.is_running = False
        self.start()
        self.function(*self.args, **self.kwargs)

    def start(self) -> None:
        """Start the thread timer."""
        if not self.is_running:
            self._timer = Timer(self.interval, self._run)
            # Daemon threads are silently killed when the main thread exits,
            # so timers don't prevent a clean process shutdown.
            self._timer.daemon = True
            self._timer.start()
            self.is_running = True

    def stop(self) -> None:
        """Stop the thread timer."""
        self._timer.cancel()
        self.is_running = False
