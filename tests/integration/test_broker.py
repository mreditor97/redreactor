"""Run the real service against a real MQTT broker, with a simulated INA219.

Skipped unless REDREACTOR_TEST_BROKER is set to a broker's `host:port`. CI
runs it against Mosquitto, with the wheel that is about to be released, so a
service that can't connect, report or take commands fails before release.

The INA219 is simulated by a stand-in `smbus2` module, found first on the
service's PYTHONPATH, that returns fixed register values: 3.9 V and 300 mA
being drawn from the battery.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import textwrap
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

BROKER = os.environ.get("REDREACTOR_TEST_BROKER", "")

pytestmark = pytest.mark.skipif(
    not BROKER,
    reason="REDREACTOR_TEST_BROKER is not set to a broker's host:port",
)

# The register values the stand-in INA219 returns. 975 x 4 mV = 3.9 V, and
# 1789 current steps of 5.5 A / 32800 is 300 mA
FAKE_SMBUS = textwrap.dedent(
    """
    REGISTERS = {0: 0, 1: 0, 2: 975 << 3, 3: 0, 4: 1789, 5: 0}


    class SMBus:
        def __init__(self, bus=None, force=False):
            self.bus = bus

        def read_i2c_block_data(self, address, register, length, force=None):
            value = REGISTERS[register]
            return [value >> 8, value & 0xFF]

        def write_i2c_block_data(self, address, register, data, force=None):
            if register in (0, 5):
                REGISTERS[register] = data[0] << 8 | data[1]
    """,
)

TIMEOUT = 15


class Recorder:
    """Collect every message the broker delivers, in order."""

    def __init__(self, host: str, port: int, topics: list[str]) -> None:
        """Connect and subscribe to the topics."""
        from paho.mqtt.client import Client
        from paho.mqtt.enums import CallbackAPIVersion

        self.messages: list[tuple[str, str, bool]] = []
        self._condition = threading.Condition()
        self._subscribed = threading.Event()
        self.client = Client(callback_api_version=CallbackAPIVersion.VERSION2)

        def on_connect(client: Any, *_: Any) -> None:
            for topic in topics:
                client.subscribe(topic, qos=1)
            self._subscribed.set()

        def on_message(_client: Any, _userdata: Any, message: Any) -> None:
            with self._condition:
                self.messages.append(
                    (message.topic, message.payload.decode(), message.retain),
                )
                self._condition.notify_all()

        self.client.on_connect = on_connect
        self.client.on_message = on_message
        self.client.connect(host, port)
        self.client.loop_start()
        assert self._subscribed.wait(TIMEOUT)

    def wait_for(
        self,
        test: Callable[[str, str], bool],
        description: str,
        after: int = 0,
    ) -> tuple[str, str]:
        """Wait for a message that passes the test and return it.

        Only the messages from index `after` on are looked at.
        """
        deadline = time.monotonic() + TIMEOUT
        with self._condition:
            while True:
                for topic, payload, _ in self.messages[after:]:
                    if test(topic, payload):
                        return topic, payload
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    seen = [topic for topic, _, _ in self.messages]
                    pytest.fail(f"No {description} within {TIMEOUT}s, saw {seen}")
                self._condition.wait(remaining)

    def stop(self) -> None:
        """Disconnect."""
        self.client.loop_stop()
        self.client.disconnect()


def _start_service(
    tmp_path: Path,
    configuration: Path,
    database: Path,
    notify_socket: Path,
) -> subprocess.Popen[str]:
    """Run the service as systemd would, with its notify socket and watchdog."""
    return subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-m",
            "redreactor",
            "--config",
            str(configuration),
            "--database",
            str(database),
            "--log",
            str(tmp_path / "redreactor.log"),
        ],
        env=os.environ
        | {
            "PYTHONPATH": str(tmp_path / "fake"),
            "NOTIFY_SOCKET": str(notify_socket),
            # A ping every second
            "WATCHDOG_USEC": "2000000",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _stop_service(service: subprocess.Popen[str]) -> str:
    """Stop the service if it is still running, and return its output.

    Returns nothing when its output has been read already.
    """
    if service.stdout is None or service.stdout.closed:
        return ""
    if service.poll() is None:
        service.kill()
    output, _ = service.communicate()
    return output


# One scenario from start to restart, as each step needs the one before
def test_service_reports_and_takes_commands(tmp_path: Path) -> None:  # noqa: PLR0915
    """Start the service, read its reports, change a setting and restart it."""
    host, _, port = BROKER.rpartition(":")
    hostname = f"ci-{uuid.uuid4().hex[:8]}"
    device = f"redreactor/{hostname}"

    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "smbus2.py").write_text(FAKE_SMBUS)
    configuration = tmp_path / "config.yaml"
    configuration.write_text(
        json.dumps(
            {
                "mqtt": {"broker": host, "port": int(port), "version": 5},
                "hostname": {"name": hostname, "pretty": "CI"},
                "ina": {"monitor_interval": 0.5},
                # Stand-ins for the real commands, so nothing is shut down
                "system": {"shutdown": "true", "restart": "true"},
                "logging": {"console": "DEBUG", "file": "WARNING"},
            },
        ),
    )
    database = tmp_path / "database.db"
    notify_socket = tmp_path / "notify"
    systemd = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    systemd.bind(str(notify_socket))
    systemd.settimeout(TIMEOUT)

    recorder = Recorder(
        host,
        int(port),
        [f"{device}/#", "homeassistant/device/+/config"],
    )
    service = _start_service(tmp_path, configuration, database, notify_socket)
    second_service: subprocess.Popen[str] | None = None
    output = ""
    try:
        recorder.wait_for(
            lambda topic, payload: topic == f"{device}/status" and payload == "online",
            "online status",
        )
        _, state = recorder.wait_for(
            lambda topic, _: topic == f"{device}/state",
            "state report",
        )
        # Started under systemd: ready, then the watchdog pings
        assert systemd.recv(64) == b"READY=1"
        assert systemd.recv(64) == b"WATCHDOG=1"

        reading = json.loads(state)
        assert reading["voltage"] == pytest.approx(3.9)
        # Published negative while the battery is discharging
        assert reading["current"] == pytest.approx(-300, abs=0.2)
        assert reading["power"] == pytest.approx(1.17, abs=0.01)
        assert reading["external_power"] == "OFF"
        assert reading["sensor_problem"] == "OFF"
        assert reading["last_shutdown"] is None

        _, discovery = recorder.wait_for(
            lambda topic, _: topic.endswith(f"redreactor_{hostname}/config")
            and topic.startswith("homeassistant/device/"),
            "device discovery",
        )
        components = json.loads(discovery)["components"]
        assert components["voltage"]["platform"] == "sensor"
        assert components["shutdown"]["platform"] == "button"
        assert components["refresh"]["platform"] == "button"

        # The refresh button sends a report straight away, rather than at the
        # next report interval (30 seconds by default)
        received = len(recorder.messages)
        recorder.client.publish(f"{device}/set/refresh", "true", qos=1)
        recorder.wait_for(
            lambda topic, _: topic == f"{device}/state",
            "report after refresh",
            after=received,
        )

        # A setting from Home Assistant is applied, reported and saved
        recorder.client.publish(f"{device}/set/report_interval", "60", qos=1)
        recorder.wait_for(
            lambda topic, payload: topic == f"{device}/state"
            and json.loads(payload)["report_interval"] == 60,
            "report with the new interval",
        )
        assert json.loads(database.read_text())["report_interval"] == 60

        # The restart button sends offline, runs the command and exits cleanly
        recorder.client.publish(f"{device}/set/restart", "true", qos=1)
        try:
            exit_code = service.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            pytest.fail("The service didn't exit after the restart command")
        assert exit_code == 0
        recorder.wait_for(
            lambda topic, payload: topic == f"{device}/status" and payload == "offline",
            "offline status",
        )
        status = [
            payload
            for topic, payload, _ in recorder.messages
            if topic.endswith("/status")
        ]
        assert status[-1] == "offline"
        output = _stop_service(service)

        # After the restart, the reason is reported as the last shutdown
        second_service = _start_service(
            tmp_path,
            configuration,
            database,
            notify_socket,
        )
        _, state = recorder.wait_for(
            lambda topic, payload: topic == f"{device}/state"
            and json.loads(payload)["last_shutdown"] is not None,
            "report with the last shutdown",
        )
        reading = json.loads(state)
        assert reading["last_shutdown"] == "Restart button"
        assert reading["last_shutdown_voltage"] == pytest.approx(3.9)
        assert reading["last_shutdown_time"].endswith("+00:00")
    finally:
        output += _stop_service(service)
        if second_service is not None:
            output += _stop_service(second_service)
        systemd.close()
        # Clear the retained messages this test left on the broker
        for topic in (f"{device}/status", f"{device}/state"):
            recorder.client.publish(topic, "", retain=True).wait_for_publish(5)
        recorder.stop()
        print(output)  # noqa: T201 Shown by pytest when the test fails
