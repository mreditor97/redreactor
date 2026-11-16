"""Tests for the Home Assistant Supervisor host actions."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from redreactor.helpers import supervisor


@pytest.mark.parametrize(
    ("command", "action"),
    [
        ("ha host shutdown", "shutdown"),
        ("ha host reboot", "reboot"),
        ("ha host restart", "reboot"),
        ("  ha   host shutdown ", "shutdown"),
        ("sudo shutdown 0 -h", None),
        ("ha host info", None),
        ("ha host shutdown --force", None),
        ("ha core restart", None),
        ("ha 'unclosed", None),
    ],
)
def test_host_action(command, action):
    """Only `ha host shutdown`, `reboot` and `restart` are Supervisor actions."""
    assert supervisor.host_action(command) == action


def test_supervisor_token(monkeypatch):
    """The token comes from SUPERVISOR_TOKEN, an empty one counts as unset."""
    monkeypatch.setenv("SUPERVISOR_TOKEN", "secret")
    assert supervisor.supervisor_token() == "secret"
    monkeypatch.setenv("SUPERVISOR_TOKEN", "")
    assert supervisor.supervisor_token() is None
    monkeypatch.delenv("SUPERVISOR_TOKEN")
    assert supervisor.supervisor_token() is None


@pytest.fixture
def fake_supervisor(monkeypatch):
    """Run a stand-in Supervisor API, recording the requests it gets."""
    requests: list[dict[str, Any]] = []
    reply: dict[str, Any] = {"status": 200, "body": {"result": "ok", "data": {}}}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 The http.server method name
            length = int(self.headers.get("Content-Length", 0))
            requests.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "body": self.rfile.read(length),
                },
            )
            body = json.dumps(reply["body"]).encode()
            self.send_response(reply["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(
        supervisor,
        "SUPERVISOR_URL",
        f"http://127.0.0.1:{server.server_port}",
    )
    yield requests, reply
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize("action", ["shutdown", "reboot"])
def test_call_host_action(fake_supervisor, action):
    """The action is posted with the token as a bearer token."""
    requests, _ = fake_supervisor

    assert supervisor.call_host_action(action, "secret", 5)

    assert requests == [
        {
            "path": f"/host/{action}",
            "authorization": "Bearer secret",
            "body": b"{}",
        },
    ]


def test_call_host_action_refused(fake_supervisor, caplog):
    """A refused request, such as without the manager role, is logged."""
    _, reply = fake_supervisor
    reply["status"] = 403
    reply["body"] = {"result": "error", "message": "Forbidden"}

    assert not supervisor.call_host_action("shutdown", "secret", 5)
    assert "HTTP 403" in caplog.text


def test_call_host_action_error_result(fake_supervisor, caplog):
    """An error result in a 200 answer is logged with its message."""
    _, reply = fake_supervisor
    reply["body"] = {"result": "error", "message": "Not now"}

    assert not supervisor.call_host_action("shutdown", "secret", 5)
    assert "Not now" in caplog.text


def test_call_host_action_no_answer(monkeypatch, caplog):
    """No answer, as when the host is already going down, is only a warning."""
    # Nothing listens on port 9 of localhost
    monkeypatch.setattr(supervisor, "SUPERVISOR_URL", "http://127.0.0.1:9")

    assert not supervisor.call_host_action("reboot", "secret", 1)
    assert "No answer from the Supervisor" in caplog.text
