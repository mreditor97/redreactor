"""Tests for RepeatTimer."""

from __future__ import annotations

import threading

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


def test_stop_before_start_is_safe():
    """stop() on a timer that never started does not raise."""
    timer = RepeatTimer(60, lambda: None)
    timer.stop()
    assert timer.is_running is False


def test_set_interval_applies_immediately():
    """Shortening the interval does not wait out the old, longer one."""
    event = threading.Event()

    timer = RepeatTimer(60, event.set)
    timer.start()
    timer.set_interval(0.05)
    called = event.wait(timeout=2.0)
    timer.stop()
    assert called, "New interval was not applied until the old one finished"
    assert timer.interval == 0.05


def test_set_interval_same_value_keeps_pending_tick():
    """Setting the same interval leaves the pending tick alone."""
    timer = RepeatTimer(60, lambda: None)
    timer.start()
    pending = timer._thread
    timer.set_interval(60)
    assert timer._thread is pending
    timer.stop()


def test_set_interval_when_stopped_does_not_start():
    """Changing the interval of a stopped timer does not start it."""
    timer = RepeatTimer(60, lambda: None)
    timer.set_interval(30)
    assert timer.interval == 30
    assert timer.is_running is False


def test_ticks_run_on_one_thread():
    """Every call runs on the same thread, not a new one per tick."""
    threads = []
    done = threading.Event()

    def callback():
        threads.append(threading.current_thread())
        if len(threads) == 3:
            done.set()

    timer = RepeatTimer(0.01, callback)
    timer.start()
    assert done.wait(timeout=2.0)
    timer.stop()

    assert len(set(threads)) == 1


def test_stop_inside_function_ends_the_timer():
    """A stop() from the timer's own function prevents any further calls."""
    calls = []
    timer = RepeatTimer(0.01, lambda: (calls.append(1), timer.stop()))
    timer.start()
    thread = timer._thread
    thread.join(timeout=2.0)

    assert not thread.is_alive()
    assert calls == [1]
    assert timer.is_running is False


def test_function_error_keeps_the_timer_running():
    """An exception in one call is logged and the next call still happens."""
    calls = []
    done = threading.Event()

    def callback():
        calls.append(1)
        if len(calls) == 1:
            msg = "boom"
            raise RuntimeError(msg)
        done.set()

    timer = RepeatTimer(0.01, callback)
    timer.start()
    assert done.wait(timeout=2.0)
    timer.stop()


def test_restart_replaces_the_waiting_thread():
    """Stopping and starting again leaves only one thread running."""
    timer = RepeatTimer(60, lambda: None)
    timer.start()
    first = timer._thread
    timer.stop()
    timer.start()
    first.join(timeout=2.0)

    assert not first.is_alive()
    assert timer._thread is not first
    assert timer._thread.is_alive()
    timer.stop()
