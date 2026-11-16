"""Tests for choosing how the device is shut down or restarted."""

from __future__ import annotations

import pytest

from redreactor.helpers import power


@pytest.fixture
def no_supervisor(monkeypatch):
    """Run outside the Home Assistant Supervisor."""
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)


@pytest.mark.parametrize(("event_type", "action"), [("shutdown", "shutdown"), ("restart", "reboot")])
@pytest.mark.parametrize("command", [None, "", "   "])
def test_automatic_under_the_supervisor(monkeypatch, event_type, action, command):
    """Left empty under the Supervisor, its API is used."""
    monkeypatch.setenv("SUPERVISOR_TOKEN", "secret")

    method = power.power_method(event_type, command)

    assert method == power.PowerMethod(supervisor_action=action, automatic=True)
    assert method.describe() == (
        f"the Supervisor API (POST /host/{action}), chosen automatically"
    )


@pytest.mark.usefixtures("no_supervisor")
@pytest.mark.parametrize(
    ("event_type", "uid", "expected"),
    [
        ("shutdown", 0, ("shutdown", "0", "-h")),
        ("restart", 0, ("shutdown", "0", "-r")),
        ("shutdown", 1000, ("sudo", "shutdown", "0", "-h")),
        ("restart", 1000, ("sudo", "shutdown", "0", "-r")),
    ],
)
def test_automatic_command(monkeypatch, event_type, uid, expected):
    """Left empty, root runs `shutdown` directly and other users through sudo."""
    monkeypatch.setattr(power.os, "geteuid", lambda: uid)

    method = power.power_method(event_type, "")

    assert method == power.PowerMethod(command=expected, automatic=True)
    assert method.describe().endswith(", chosen automatically")


@pytest.mark.usefixtures("no_supervisor")
def test_set_command_is_used_as_it_is():
    """A command that is set is split and run as it is."""
    method = power.power_method("shutdown", "systemctl poweroff --no-wall")

    assert method == power.PowerMethod(
        command=("systemctl", "poweroff", "--no-wall"),
    )
    assert method.describe() == "`systemctl poweroff --no-wall`"


def test_ha_host_command_under_the_supervisor(monkeypatch):
    """An `ha host` command under the Supervisor goes to its API."""
    monkeypatch.setenv("SUPERVISOR_TOKEN", "secret")

    method = power.power_method("restart", "ha host restart")

    assert method == power.PowerMethod(supervisor_action="reboot")
    assert method.describe() == "the Supervisor API (POST /host/reboot)"


@pytest.mark.usefixtures("no_supervisor")
def test_unsplittable_command():
    """A command shlex can't split gives no command, which is described."""
    method = power.power_method("shutdown", "echo 'oops")

    assert method == power.PowerMethod()
    assert "can't be split" in method.describe()


@pytest.mark.parametrize(
    ("command", "automatic"),
    [(None, True), ("", True), (" \t", True), ("shutdown 0 -h", False)],
)
def test_is_automatic(command, automatic):
    """Only an empty command is filled in."""
    assert power.is_automatic(command) is automatic
