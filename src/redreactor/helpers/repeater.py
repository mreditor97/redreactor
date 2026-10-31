"""Repeat Timer module."""

from threading import RLock, Timer
from typing import Any


class RepeatTimer:
    """Repeat Timer."""

    _timer: Timer | None

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
        self._timer = None
        # Guards start/stop/set_interval, which can be called from the MQTT
        # thread while the timer thread is rescheduling itself.
        self._lock = RLock()

    def _run(self) -> None:
        """Run timer."""
        # Schedule the next tick BEFORE invoking the callback so the interval
        # is measured from the start of each call, not the end.  It also means
        # a stop() issued from inside the callback will cancel the already-
        # queued next timer rather than being silently ignored.
        with self._lock:
            self.is_running = False
            self.start()
        self.function(*self.args, **self.kwargs)

    def start(self) -> None:
        """Start the thread timer."""
        with self._lock:
            if not self.is_running:
                self._timer = Timer(self.interval, self._run)
                # Daemon threads are silently killed when the main thread
                # exits, so timers don't prevent a clean process shutdown.
                self._timer.daemon = True
                self._timer.start()
                self.is_running = True

    def stop(self) -> None:
        """Stop the thread timer."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self.is_running = False

    def set_interval(self, interval: float) -> None:
        """Change the interval, applying it straight away.

        Assigning ``interval`` directly only takes effect after the tick that
        is already waiting has fired, so a change from a long interval to a
        short one could sit unused for the whole of the old interval.  When
        the timer is running and the interval has changed, the pending tick
        is cancelled and a new one is scheduled ``interval`` seconds from now.
        """
        with self._lock:
            if interval == self.interval:
                return
            self.interval = interval
            if self.is_running:
                self.stop()
                self.start()
