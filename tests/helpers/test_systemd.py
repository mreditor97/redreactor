"""Tests for the systemd notify and watchdog helpers."""

from __future__ import annotations

import os
import socket
from unittest.mock import MagicMock, patch

import pytest

from redreactor.helpers import systemd


@pytest.fixture
def notify_socket(tmp_path, monkeypatch):
    """Listen on a Unix datagram socket, as systemd does."""
    path = tmp_path / "notify"
    receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    receiver.bind(str(path))
    receiver.settimeout(5)
    monkeypatch.setenv("NOTIFY_SOCKET", str(path))
    yield receiver
    receiver.close()


def test_notify_sends_the_message(notify_socket):
    """The message is sent as one datagram."""
    assert systemd.notify("READY=1")
    assert notify_socket.recv(64) == b"READY=1"


def test_notify_without_systemd_does_nothing(monkeypatch):
    """Outside systemd there is no socket, and nothing is sent."""
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert not systemd.notify("READY=1")


def test_notify_ignores_other_socket_types(monkeypatch):
    """Only Unix socket paths are used, not vsock addresses."""
    monkeypatch.setenv("NOTIFY_SOCKET", "vsock:2:1234")
    assert not systemd.notify("READY=1")


def test_notify_uses_the_abstract_namespace(monkeypatch):
    """A name starting with @ is an abstract socket, with a leading NUL."""
    monkeypatch.setenv("NOTIFY_SOCKET", "@redreactor-test")
    connection = MagicMock()
    with patch.object(systemd.socket, "socket") as socket_class:
        socket_class.return_value.__enter__.return_value = connection
        assert systemd.notify("WATCHDOG=1")

    connection.connect.assert_called_once_with("\0redreactor-test")
    connection.sendall.assert_called_once_with(b"WATCHDOG=1")


def test_notify_failure_is_not_raised(tmp_path, monkeypatch):
    """A socket that can't be reached doesn't stop the service."""
    monkeypatch.setenv("NOTIFY_SOCKET", str(tmp_path / "missing"))
    assert not systemd.notify("READY=1")


@pytest.mark.parametrize(
    ("usec", "pid", "expected"),
    [
        ("60000000", None, 30.0),
        ("60000000", "own", 30.0),
        ("60000000", "1", None),
        (None, None, None),
        ("soon", None, None),
        ("0", None, None),
    ],
)
def test_watchdog_interval(monkeypatch, usec, pid, expected):
    """Pings are sent at half the watchdog time, for this process only."""
    monkeypatch.delenv("WATCHDOG_USEC", raising=False)
    monkeypatch.delenv("WATCHDOG_PID", raising=False)
    if usec is not None:
        monkeypatch.setenv("WATCHDOG_USEC", usec)
    if pid is not None:
        monkeypatch.setenv("WATCHDOG_PID", str(os.getpid()) if pid == "own" else pid)

    assert systemd.watchdog_interval() == expected


def test_watchdog_not_started_without_systemd(monkeypatch):
    """No timer runs when the watchdog isn't enabled."""
    monkeypatch.delenv("WATCHDOG_USEC", raising=False)
    assert systemd.start_watchdog(lambda: True) is None


def test_watchdog_pings_only_while_healthy(monkeypatch, notify_socket):
    """WATCHDOG=1 is sent while healthy, and stops when the readings stop."""
    monkeypatch.setenv("WATCHDOG_USEC", "60000000")
    healthy = [True]
    with patch.object(systemd, "RepeatTimer") as timer_class:
        timer = systemd.start_watchdog(lambda: healthy[0])

    assert timer is timer_class.return_value
    timer.start.assert_called_once()
    interval, ping = timer_class.call_args.args
    assert interval == 30.0

    ping()
    assert notify_socket.recv(64) == b"WATCHDOG=1"

    healthy[0] = False
    ping()
    notify_socket.settimeout(0.1)
    with pytest.raises(TimeoutError):
        notify_socket.recv(64)
