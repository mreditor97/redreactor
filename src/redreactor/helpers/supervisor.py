"""Shut down or restart the host through the Home Assistant Supervisor.

Running as a Home Assistant app, the Supervisor gives the app a token in
`SUPERVISOR_TOKEN`, and its API is at `http://supervisor`. `ha host shutdown`
and `ha host reboot` are the CLI for its `POST /host/shutdown` and
`POST /host/reboot`, so the same can be done without the `ha` binary. The app
needs `hassio_api: true` and a `hassio_role` that covers the host, `manager`.

Outside the Supervisor the token isn't set, and the configured command is run
as before, such as `sudo shutdown 0 -h`.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import urllib.error
import urllib.request
from typing import Literal

logger = logging.getLogger("Red Reactor")

SUPERVISOR_URL = "http://supervisor"

# `ha host` commands and the Supervisor API endpoint each one calls. The CLI
# accepts `restart` for `reboot`.
HOST_ACTIONS: dict[str, Literal["shutdown", "reboot"]] = {
    "shutdown": "shutdown",
    "reboot": "reboot",
    "restart": "reboot",
}


def supervisor_token() -> str | None:
    """Return the Supervisor API token, None when not running under it."""
    return os.environ.get("SUPERVISOR_TOKEN") or None


def host_action(command: str) -> Literal["shutdown", "reboot"] | None:
    """Return the host action of an `ha host` command, such as `ha host shutdown`.

    None for any other command, which is then run as it is.
    """
    try:
        arguments = shlex.split(command)
    except ValueError:
        return None
    if len(arguments) != 3 or arguments[:2] != ["ha", "host"]:  # noqa: PLR2004
        return None
    return HOST_ACTIONS.get(arguments[2])


def call_host_action(
    action: Literal["shutdown", "reboot"],
    token: str,
    timeout: float,
) -> bool:
    """Ask the Supervisor to shut down or reboot the host.

    Returns whether the Supervisor accepted it. The host can go down before
    the answer arrives, so a dropped connection is logged but not an error.
    """
    request = urllib.request.Request(  # noqa: S310 A fixed http://supervisor URL
        f"{SUPERVISOR_URL}/host/{action}",
        data=b"{}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        logger.error(  # noqa: TRY400
            "The Supervisor refused the host %s (HTTP %i), the app needs the "
            "manager role",
            action,
            error.code,
        )
        return False
    except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
        logger.warning(
            "No answer from the Supervisor to the host %s (%s), the host may "
            "already be going down",
            action,
            error,
        )
        return False
    except json.JSONDecodeError:
        body = {}

    if body.get("result", "ok") != "ok":
        logger.error(
            "The Supervisor didn't run the host %s: %s",
            action,
            body.get("message", body),
        )
        return False
    return True
