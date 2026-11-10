"""Repeat Timer module."""

from __future__ import annotations

import logging
import time
from threading import Condition, RLock, Thread
from typing import Any

logger = logging.getLogger("Red Reactor")


class RepeatTimer:
    """Call a function every `interval` seconds on one long-lived thread.

    A `threading.Timer` per tick would start a new thread every interval, which
    for the 5 second monitor interval is about 17,000 threads a day. One thread
    waits on a condition instead, and is only replaced when the timer is
    stopped and started again or its interval changes.
    """

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
        self._thread: Thread | None = None
        # Guards start/stop/set_interval, which can be called from the MQTT
        # thread while the timer thread is waiting or running the function.
        self._lock = RLock()
        self._wakeup = Condition(self._lock)
        # Increased on every stop, so a waiting thread from an earlier start
        # knows it has been replaced and ends
        self._generation = 0

    def _run(self, generation: int) -> None:
        """Wait out each interval and call the function, until stopped."""
        next_call = time.monotonic() + self.interval
        while True:
            with self._lock:
                while self._generation == generation:
                    remaining = next_call - time.monotonic()
                    if remaining <= 0:
                        break
                    self._wakeup.wait(remaining)
                if self._generation != generation:
                    return
                # The next call is measured from the start of this one, not
                # the end, so the interval doesn't drift by how long it takes
                next_call = time.monotonic() + self.interval

            try:
                self.function(*self.args, **self.kwargs)
            except Exception:
                # The timer must keep running, as a reading that raises once
                # would otherwise stop the battery monitoring for good
                logger.exception(
                    "Error in the timer function %s",
                    getattr(self.function, "__qualname__", self.function),
                )

    def start(self) -> None:
        """Start the timer, the first call is one interval from now."""
        with self._lock:
            if self.is_running:
                return
            self.is_running = True
            self._thread = Thread(
                target=self._run,
                args=(self._generation,),
                name=f"redreactor-timer-{getattr(self.function, '__name__', '')}",
                # Daemon threads are silently killed when the main thread
                # exits, so timers don't prevent a clean process shutdown.
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Stop the timer, including from inside the timer's own function."""
        with self._lock:
            self._generation += 1
            self.is_running = False
            self._wakeup.notify_all()

    def set_interval(self, interval: float) -> None:
        """Change the interval, applying it straight away.

        When the timer is running and the interval has changed, the pending
        call is dropped and the next one is `interval` seconds from now, so a
        change from a long interval to a short one doesn't wait out the old one.
        """
        with self._lock:
            if interval == self.interval:
                return
            self.interval = interval
            if self.is_running:
                self.stop()
                self.start()
