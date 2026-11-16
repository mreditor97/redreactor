"""Work out how the device is shut down or restarted.

`system.shutdown` and `system.restart` left empty are filled in automatically:

- under the Home Assistant Supervisor, its API (see `supervisor`)
- running as root, `shutdown 0 -h` or `shutdown 0 -r`
- otherwise the same through `sudo -n`, which needs a sudoers entry for the
  user. `-n` fails straight away without one, rather than asking for a password

A command that is set is run as it is, apart from an `ha host` command under
the Supervisor, which is sent to its API so the `ha` CLI isn't needed.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from typing import Literal

from redreactor.helpers import supervisor

ROOT_UID = 0

# The shutdown flag and Supervisor host action for each event
EVENTS: dict[str, tuple[str, Literal["shutdown", "reboot"]]] = {
    "shutdown": ("-h", "shutdown"),
    "restart": ("-r", "reboot"),
}


@dataclass(frozen=True)
class PowerMethod:
    """How a shutdown or restart is done: a Supervisor action or a command."""

    supervisor_action: Literal["shutdown", "reboot"] | None = None
    command: tuple[str, ...] = ()
    automatic: bool = False

    def describe(self) -> str:
        """Describe the method for the log."""
        if self.supervisor_action:
            how = f"the Supervisor API (POST /host/{self.supervisor_action})"
        elif not self.command:
            how = "nothing, the command can't be split into arguments"
        else:
            how = f"`{shlex.join(self.command)}`"
        return f"{how}, chosen automatically" if self.automatic else how


def is_automatic(command: str | None) -> bool:
    """Return whether a configured command is left empty, to be filled in."""
    return command is None or not command.strip()


def power_method(
    event_type: Literal["shutdown", "restart"],
    command: str | None,
) -> PowerMethod:
    """Return how to shut down or restart, from the configured command.

    The configuration checks the command splits with shlex. One that
    doesn't is returned with no command, which is logged when it is needed.
    """
    flag, action = EVENTS[event_type]
    under_supervisor = supervisor.supervisor_token() is not None

    if command is not None and not is_automatic(command):
        host_action = supervisor.host_action(command)
        if under_supervisor and host_action:
            return PowerMethod(supervisor_action=host_action)
        try:
            return PowerMethod(command=tuple(shlex.split(command)))
        except ValueError:
            return PowerMethod()

    if under_supervisor:
        return PowerMethod(supervisor_action=action, automatic=True)

    arguments: tuple[str, ...] = ("shutdown", "0", flag)
    if os.geteuid() != ROOT_UID:
        arguments = ("sudo", "-n", *arguments)
    return PowerMethod(command=arguments, automatic=True)
