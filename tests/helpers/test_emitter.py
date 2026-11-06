"""Tests for EventEmitter."""

from __future__ import annotations

from unittest.mock import MagicMock

from redreactor.helpers.emitter import EventEmitter


def test_register_and_fire_callback():
    """Registering and firing a callback calls it."""
    emitter = EventEmitter()
    cb = MagicMock()
    emitter.on("test", cb)
    emitter.emit("test")
    cb.assert_called_once()


def test_multiple_callbacks_on_same_event():
    """Multiple callbacks registered on the same event are all called."""
    emitter = EventEmitter()
    cb1 = MagicMock()
    cb2 = MagicMock()
    emitter.on("multi", cb1)
    emitter.on("multi", cb2)
    emitter.emit("multi")
    cb1.assert_called_once()
    cb2.assert_called_once()


def test_off_removes_callback():
    """off() removes a callback so it is no longer called."""
    emitter = EventEmitter()
    cb = MagicMock()
    emitter.on("evt", cb)
    emitter.off("evt", cb)
    emitter.emit("evt")
    cb.assert_not_called()


def test_emit_with_no_listeners_is_safe():
    """Emitting an event with no listeners does not raise."""
    emitter = EventEmitter()
    emitter.emit("no_listeners")  # Should not raise


def test_emit_passes_args_and_kwargs():
    """Emitting with positional and keyword args passes them through."""
    emitter = EventEmitter()
    cb = MagicMock()
    emitter.on("data", cb)
    emitter.emit("data", 1, 2, key="value")
    cb.assert_called_once_with(1, 2, key="value")


def test_failing_listener_does_not_stop_the_others(caplog):
    """A listener that raises is logged, and the later listeners still run.

    Most events are emitted from paho callbacks, where an exception would end
    the MQTT loop and stop the service.
    """
    emitter = EventEmitter()
    later = MagicMock()
    emitter.on("test", MagicMock(side_effect=RuntimeError("boom")))
    emitter.on("test", later)

    emitter.emit("test", 1, key="value")

    later.assert_called_once_with(1, key="value")
    assert "Error in the test listener" in caplog.text


def test_system_exit_from_a_listener_is_not_caught():
    """A deliberate exit inside a listener still exits."""
    import pytest

    emitter = EventEmitter()
    emitter.on("test", MagicMock(side_effect=SystemExit(1)))

    with pytest.raises(SystemExit):
        emitter.emit("test")
