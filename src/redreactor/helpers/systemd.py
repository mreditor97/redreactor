"""Tell systemd how the service is doing, through its notify socket.

With `Type=notify` systemd waits for `READY=1` before it treats the service as
started, and with `WatchdogSec=` it restarts the service when `WATCHDOG=1`
stops arriving. systemd passes the socket in `NOTIFY_SOCKET`, and the watchdog
time in microseconds in `WATCHDOG_USEC`. Outside systemd neither is set and
nothing is sent.

This is the sd_notify(3) protocol, a datagram on a Unix socket, so it needs no
extra dependency. A socket name starting with `@` is in the abstract namespace.
"""

from __future__ import annotations

import logging
import os
import socket
from typing import TYPE_CHECKING

from redreactor.helpers.repeater import RepeatTimer

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger("Red Reactor")

MICROSECONDS = 1_000_000


def notify(message: str) -> bool:
    """Send a message such as `READY=1` to systemd, returns whether it was sent."""
    address = os.environ.get("NOTIFY_SOCKET", "")
    # Only Unix socket paths are handled, not the vsock addresses systemd can
    # also pass to virtual machines
    if not address or address[0] not in "/@":
        return False
    if address[0] == "@":
        address = "\0" + address[1:]

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notify_socket:
            notify_socket.connect(address)
            notify_socket.sendall(message.encode())
    except OSError as error:
        logger.debug("Unable to notify systemd of %s (%s)", message, error)
        return False
    return True


def watchdog_interval() -> float | None:
    """Return the seconds between watchdog pings, None when it isn't enabled.

    systemd recommends pinging at half the watchdog time. `WATCHDOG_PID` names
    the process the watchdog is for, when it is set.
    """
    pid = os.environ.get("WATCHDOG_PID")
    if pid and pid != str(os.getpid()):
        return None
    try:
        microseconds = int(os.environ.get("WATCHDOG_USEC", ""))
    except ValueError:
        return None
    if microseconds <= 0:
        return None
    return microseconds / MICROSECONDS / 2


def start_watchdog(is_healthy: Callable[[], bool]) -> RepeatTimer | None:
    """Ping the systemd watchdog while `is_healthy()` is true.

    The pings come from their own timer, so a monitor interval longer than the
    watchdog time still works. When the readings stop (such as an I2C read
    that never returns) `is_healthy()` turns false, the pings stop and systemd
    restarts the service.
    """
    interval = watchdog_interval()
    if interval is None:
        return None

    def ping() -> None:
        if is_healthy():
            notify("WATCHDOG=1")
        else:
            logger.error("The battery readings have stopped, not pinging systemd")

    logger.info("Pinging the systemd watchdog every %ss", interval)
    timer = RepeatTimer(interval, ping)
    timer.start()
    return timer
