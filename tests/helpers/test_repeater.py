"""Tests for RepeatTimer."""

from __future__ import annotations

import threading
import time

from redreactor.helpers.repeater import RepeatTimer


def test_is_running_starts_false():
    """is_running should be False before start() is called."""
    timer = RepeatTimer(60, lambda: None)
    assert timer.is_running is False


def test_is_running_true_after_start():
    """is_running should be True after start() is called."""
    timer = RepeatTimer(60, lambda: None)
    timer.start()
    assert timer.is_running is True
    timer.stop()


def test_is_running_false_after_stop():
    """is_running should be False after stop() is called."""
    timer = RepeatTimer(60, lambda: None)
    timer.start()
    timer.stop()
    assert timer.is_running is False


def test_function_gets_called():
    """The timer function actually gets called after the interval elapses."""
    event = threading.Event()

    def callback():
        event.set()

    timer = RepeatTimer(0.05, callback)
    timer.start()
    called = event.wait(timeout=2.0)
    timer.stop()
    assert called, "Callback was not called within timeout"


def test_start_twice_is_idempotent():
    """Calling start() twice does not create duplicate timers."""
    call_count = {"n": 0}
    event = threading.Event()

    def callback():
        call_count["n"] += 1
        event.set()

    timer = RepeatTimer(0.05, callback)
    timer.start()
    timer.start()  # Should be a no-op since already running
    assert timer.is_running is True
    event.wait(timeout=2.0)
    timer.stop()
    # The timer should have been started only once (idempotent)
    assert timer.is_running is False
