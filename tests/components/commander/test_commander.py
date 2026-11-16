"""Tests for the Commander component."""

from __future__ import annotations

import json
import threading
from unittest.mock import MagicMock, patch

import pytest

from redreactor.helpers.emitter import EventEmitter

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_mock_message(topic: str, payload: str) -> MagicMock:
    """Build a fake paho MQTTMessage."""
    msg = MagicMock()
    msg.topic = topic
    msg.payload = payload.encode("utf-8")
    return msg


@pytest.fixture(autouse=True)
def reset_mqtt_and_monitor_events():
    """Reset class-level EventEmitters on MQTT and Monitor before each test."""
    from redreactor.components.monitor.monitor import Monitor
    from redreactor.components.mqtt import MQTT

    MQTT.event = EventEmitter()
    Monitor.event = EventEmitter()
    yield
    MQTT.event = EventEmitter()
    Monitor.event = EventEmitter()


@pytest.fixture
def commander(static_config, dynamic_config):
    """Return a Commander instance with mocked Monitor."""
    from redreactor.components.commander.commander import Commander
    from redreactor.components.monitor.monitor import Monitor

    mock_monitor = MagicMock()
    mock_monitor.event = Monitor.event  # Use the class-level emitter

    cmd = Commander(
        static_configuration=static_config,
        dynamic_configuration=dynamic_config,
        monitor=mock_monitor,
    )
    return cmd, mock_monitor


# ---------------------------------------------------------------------------
# _on_connect
# ---------------------------------------------------------------------------


def test_on_connect_subscribes_to_button_and_number_fields(commander, static_config):
    """_on_connect subscribes to all button and number field topics."""
    cmd, _ = commander
    mock_client = MagicMock()

    cmd._on_connect(mock_client, None, None, 0)

    subscribed_topics = [
        call.kwargs["topic"] for call in mock_client.subscribe.call_args_list
    ]

    # Should subscribe to button fields (restart, shutdown) and number fields
    base = static_config["mqtt"]["base_topic"]
    host = static_config["hostname"]["name"]
    set_topic = static_config["mqtt"]["topic"]["set"]

    for field_name, field in static_config["fields"].items():
        if field["type"] in {"button", "number"}:
            expected = f"{base}/{host}/{set_topic}/{field['name']}"
            missing = f"Missing subscription for {field_name}"
            assert expected in subscribed_topics, missing


# ---------------------------------------------------------------------------
# _on_message --- button field
# ---------------------------------------------------------------------------


def test_on_message_button_calls_on_command(commander, static_config):
    """_on_message with a button topic calls _on_command."""
    cmd, _ = commander
    base = static_config["mqtt"]["base_topic"]
    host = static_config["hostname"]["name"]
    set_topic = static_config["mqtt"]["topic"]["set"]
    topic = f"{base}/{host}/{set_topic}/shutdown"

    msg = _make_mock_message(topic, json.dumps("PRESS"))

    with patch.object(cmd, "_on_command") as mock_cmd:
        cmd._on_message(None, None, msg)
        # The command runs on its own thread, wait for it to finish
        for thread in threading.enumerate():
            if thread.name == "redreactor-shutdown":
                thread.join(timeout=5)

    mock_cmd.assert_called_once_with(event_type="shutdown")


def test_on_message_button_runs_off_the_mqtt_thread(commander, static_config):
    """Button commands are not run inside the paho on_message callback."""
    cmd, _ = commander
    base = static_config["mqtt"]["base_topic"]
    host = static_config["hostname"]["name"]
    set_topic = static_config["mqtt"]["topic"]["set"]
    topic = f"{base}/{host}/{set_topic}/restart"

    msg = _make_mock_message(topic, json.dumps("PRESS"))

    target = "redreactor.components.commander.commander.threading.Thread"
    with patch(target) as mock_thread, patch.object(cmd, "_on_command") as mock_cmd:
        cmd._on_message(None, None, msg)

    mock_cmd.assert_not_called()
    mock_thread.assert_called_once()
    assert mock_thread.call_args.kwargs["target"] is mock_cmd
    assert mock_thread.call_args.kwargs["kwargs"] == {"event_type": "restart"}
    mock_thread.return_value.start.assert_called_once()


# ---------------------------------------------------------------------------
# _on_message --- number field
# ---------------------------------------------------------------------------


def test_on_message_number_updates_dynamic_config(commander, static_config):
    """_on_message with a number topic updates dynamic_config.data."""
    cmd, _ = commander
    base = static_config["mqtt"]["base_topic"]
    host = static_config["hostname"]["name"]
    set_topic = static_config["mqtt"]["topic"]["set"]
    topic = f"{base}/{host}/{set_topic}/report_interval"

    msg = _make_mock_message(topic, json.dumps(60))

    cmd._on_message(None, None, msg)

    assert cmd._dynamic_configuration.data["report_interval"] == 60


def _send_number(cmd, static_config, field: str, payload: str) -> None:
    base = static_config["mqtt"]["base_topic"]
    host = static_config["hostname"]["name"]
    set_topic = static_config["mqtt"]["topic"]["set"]
    msg = _make_mock_message(f"{base}/{host}/{set_topic}/{field}", payload)
    cmd._on_message(None, None, msg)


@pytest.mark.parametrize(
    "payload",
    ['"abc"', "null", "true", "[30]", '{"value": 30}', "NaN", "Infinity"],
)
def test_on_message_number_rejects_non_numbers(commander, static_config, payload):
    """Non-numeric number commands are not stored or written to disk."""
    cmd, _ = commander
    written = []
    cmd._dynamic_configuration.event.on("write", lambda: written.append(True))

    _send_number(cmd, static_config, "report_interval", payload)

    assert cmd._dynamic_configuration.data["report_interval"] == 30
    assert not written


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("report_interval", 0),
        ("report_interval", 301),
        ("battery_warning_threshold", -1),
        ("battery_voltage_minimum", 2.4),
        ("battery_voltage_maximum", 4.6),
        ("battery_capacity", -1),
        ("battery_capacity", 20001),
    ],
)
def test_on_message_number_rejects_out_of_range(commander, static_config, field, value):
    """Number commands outside the field's min/max are ignored."""
    cmd, _ = commander
    before = cmd._dynamic_configuration.data[field]

    _send_number(cmd, static_config, field, json.dumps(value))

    assert cmd._dynamic_configuration.data[field] == before


def test_on_message_rejects_minimum_voltage_above_maximum(commander, static_config):
    """A minimum voltage at or above the maximum would disable low battery shutdown."""
    cmd, _ = commander

    _send_number(cmd, static_config, "battery_voltage_minimum", "4.5")
    _send_number(cmd, static_config, "battery_voltage_maximum", "2.9")

    assert cmd._dynamic_configuration.data["battery_voltage_minimum"] == 2.9
    assert cmd._dynamic_configuration.data["battery_voltage_maximum"] == 4.2


def test_on_message_accepts_valid_voltage_change(commander, static_config):
    """A valid voltage within range and below the maximum is stored."""
    cmd, _ = commander

    _send_number(cmd, static_config, "battery_voltage_minimum", "3.1")

    assert cmd._dynamic_configuration.data["battery_voltage_minimum"] == 3.1


# ---------------------------------------------------------------------------
# _on_message --- invalid JSON
# ---------------------------------------------------------------------------


def test_on_message_invalid_json_logs_warning(commander, static_config):
    """_on_message with invalid JSON logs a warning and does not crash."""
    cmd, _ = commander
    base = static_config["mqtt"]["base_topic"]
    host = static_config["hostname"]["name"]
    set_topic = static_config["mqtt"]["topic"]["set"]
    topic = f"{base}/{host}/{set_topic}/report_interval"

    msg = _make_mock_message(topic, "not valid json {{{")

    with patch.object(cmd.logger, "warning") as mock_warn:
        cmd._on_message(None, None, msg)

    mock_warn.assert_called_once()


def test_on_message_non_utf8_payload_logs_warning(commander, static_config):
    """A payload that isn't UTF-8 is logged, not raised into the MQTT loop."""
    cmd, _ = commander
    base = static_config["mqtt"]["base_topic"]
    host = static_config["hostname"]["name"]
    set_topic = static_config["mqtt"]["topic"]["set"]
    before = dict(cmd._dynamic_configuration.data)

    msg = _make_mock_message(f"{base}/{host}/{set_topic}/report_interval", "")
    msg.payload = b"\xff\xfe"

    with patch.object(cmd.logger, "warning") as mock_warn:
        cmd._on_message(None, None, msg)

    mock_warn.assert_called_once()
    assert cmd._dynamic_configuration.data == before


# ---------------------------------------------------------------------------
# _on_message --- unknown topic
# ---------------------------------------------------------------------------


def test_on_message_unknown_topic_logs_warning(commander, static_config):
    """_on_message with an unknown topic logs a warning."""
    cmd, _ = commander
    base = static_config["mqtt"]["base_topic"]
    host = static_config["hostname"]["name"]
    set_topic = static_config["mqtt"]["topic"]["set"]
    topic = f"{base}/{host}/{set_topic}/unknown_field_xyz"

    msg = _make_mock_message(topic, json.dumps("value"))

    with patch.object(cmd.logger, "warning") as mock_warn:
        cmd._on_message(None, None, msg)

    mock_warn.assert_called_once()


# ---------------------------------------------------------------------------
# _on_command
# ---------------------------------------------------------------------------


def test_on_command_shutdown_emits_publish_and_exits(commander):
    """_on_command('shutdown') publishes offline, runs the command, disconnects."""
    cmd, _ = commander
    from redreactor.components.mqtt import MQTT

    publish_calls: list[tuple[str, str]] = []
    MQTT.event.on(
        "publish",
        lambda topic, payload, **_: publish_calls.append((topic, payload)),
    )

    disconnect_calls: list[bool] = []
    MQTT.event.on("disconnect", lambda: disconnect_calls.append(True))

    target = "redreactor.components.commander.commander.subprocess.run"
    with patch(target) as mock_run, patch("time.sleep"):
        cmd._on_command("shutdown")

    assert publish_calls, "publish event was not emitted"
    mock_run.assert_called_once()
    assert disconnect_calls == [True]


def test_on_command_restart_emits_publish_and_exits(commander):
    """_on_command('restart') publishes offline, runs the command, disconnects."""
    cmd, _ = commander
    from redreactor.components.mqtt import MQTT

    publish_calls: list[tuple[str, str]] = []
    MQTT.event.on(
        "publish",
        lambda topic, payload, **_: publish_calls.append((topic, payload)),
    )

    disconnect_calls: list[bool] = []
    MQTT.event.on("disconnect", lambda: disconnect_calls.append(True))

    target = "redreactor.components.commander.commander.subprocess.run"
    with patch(target) as mock_run, patch("time.sleep"):
        cmd._on_command("restart")

    assert publish_calls
    mock_run.assert_called_once()
    assert disconnect_calls == [True]


def test_on_command_invalid_raises_value_error(commander):
    """_on_command with an invalid event_type raises ValueError."""
    cmd, _ = commander

    with pytest.raises(ValueError, match="Invalid device command"):
        cmd._on_command("invalid")


def test_on_message_ignores_topics_outside_the_set_prefix(commander):
    """Messages for other components (e.g. HA's birth message) are not commands."""
    cmd, _ = commander
    msg = _make_mock_message("homeassistant/status", "online")

    with patch.object(cmd.logger, "warning") as mock_warn:
        cmd._on_message(None, None, msg)

    mock_warn.assert_not_called()


def test_on_command_logs_failed_system_command(commander):
    """A failing shutdown command is logged rather than silently ignored."""
    cmd, _ = commander
    from redreactor.components.mqtt import MQTT

    MQTT.event.on("publish", lambda **_: None)

    target = "redreactor.components.commander.commander.subprocess.run"
    with (
        patch(target) as mock_run,
        patch("time.sleep"),
        patch.object(cmd.logger, "error") as mock_error,
    ):
        mock_run.return_value.returncode = 1
        cmd._on_command("shutdown")

    mock_error.assert_called_once()


def test_on_command_logs_missing_system_command(commander):
    """A system command that can't be started is logged, then still disconnects."""
    cmd, _ = commander
    from redreactor.components.mqtt import MQTT

    MQTT.event.on("publish", lambda **_: None)
    disconnect_calls: list[bool] = []
    MQTT.event.on("disconnect", lambda: disconnect_calls.append(True))

    target = "redreactor.components.commander.commander.subprocess.run"
    with (
        patch(target, side_effect=FileNotFoundError("sudo")),
        patch("time.sleep"),
        patch.object(cmd.logger, "exception") as mock_exception,
    ):
        cmd._on_command("shutdown")

    mock_exception.assert_called_once()
    assert disconnect_calls == [True]


def test_on_message_matches_renamed_field_name(static_config, dynamic_config):
    """Commands are matched on the configured field name, stored by field key."""
    from redreactor.components.commander.commander import Commander

    static_config["fields"]["report_interval"]["name"] = "interval_seconds"
    cmd = Commander(static_config, dynamic_config, MagicMock())

    _send_number(cmd, static_config, "interval_seconds", "60")

    assert cmd._dynamic_configuration.data["report_interval"] == 60


def test_on_message_requires_exact_field_name(commander, static_config):
    """A topic that only contains a field name is not treated as that field."""
    cmd, _ = commander

    with patch.object(cmd.logger, "warning") as mock_warn:
        _send_number(cmd, static_config, "report_interval_extra", "60")

    assert cmd._dynamic_configuration.data["report_interval"] == 30
    mock_warn.assert_called_once()


def test_on_message_sets_battery_capacity(commander, static_config):
    """The battery capacity can be changed from Home Assistant."""
    cmd, _ = commander

    _send_number(cmd, static_config, "battery_capacity", "3000")

    assert cmd._dynamic_configuration.data["battery_capacity"] == 3000


def test_on_command_shutdown_publishes_shutdown_started_first(commander):
    """A shutdown sends the shutdown started event before going offline."""
    cmd, mock_monitor = commander
    from redreactor.components.mqtt import MQTT

    order: list[str] = []
    mock_monitor.publish_event.side_effect = order.append
    MQTT.event.on("publish", lambda payload, **_: order.append(payload))

    target = "redreactor.components.commander.commander.subprocess.run"
    with patch(target), patch("time.sleep"):
        cmd._on_command("shutdown")

    assert order[:2] == ["shutdown_started", "offline"]


def test_on_command_restart_sends_no_shutdown_event(commander):
    """A restart isn't a shutdown, so no shutdown started event is sent."""
    cmd, mock_monitor = commander

    target = "redreactor.components.commander.commander.subprocess.run"
    with patch(target), patch("time.sleep"):
        cmd._on_command("restart")

    mock_monitor.publish_event.assert_not_called()


def test_second_shutdown_is_ignored(commander):
    """A shutdown already running isn't started again."""
    cmd, mock_monitor = commander

    target = "redreactor.components.commander.commander.subprocess.run"
    with patch(target) as mock_run, patch("time.sleep"):
        cmd._on_command("shutdown")
        cmd._on_command("shutdown")
        cmd._on_command("restart")

    mock_run.assert_called_once()
    mock_monitor.publish_event.assert_called_once_with("shutdown_started")


@pytest.mark.parametrize("event_type", ["shutdown", "restart"])
def test_on_command_stops_the_monitor_before_going_offline(commander, event_type):
    """The monitor stops first, so it can't publish online after offline."""
    cmd, mock_monitor = commander
    from redreactor.components.mqtt import MQTT

    order: list[str] = []
    mock_monitor.stop.side_effect = lambda: order.append("stop")
    MQTT.event.on("publish", lambda payload, **_: order.append(payload))

    target = "redreactor.components.commander.commander.subprocess.run"
    with patch(target), patch("time.sleep"):
        cmd._on_command(event_type)

    assert order.index("stop") < order.index("offline")


def test_on_message_ignores_a_large_payload(commander, static_config, dynamic_config):
    """A payload far larger than a number is refused before it is decoded."""
    cmd, _ = commander
    topic = "/".join(
        (
            static_config["mqtt"]["base_topic"],
            static_config["hostname"]["name"],
            static_config["mqtt"]["topic"]["set"],
            "report_interval",
        ),
    )
    before = dict(dynamic_config.data)

    with patch.object(cmd.logger, "warning") as mock_warn:
        cmd._on_message(None, None, _make_mock_message(topic, "1" * 10_000))

    assert "too large" in mock_warn.call_args.args[0]
    assert dynamic_config.data == before


def test_on_message_deeply_nested_json_is_ignored(commander, static_config):
    """Nested JSON that raises RecursionError is only logged.

    The size limit already stops this payload, so the limit is raised here to
    check the decode error is caught too. It used to stop the service.
    """
    cmd, _ = commander
    topic = "/".join(
        (
            static_config["mqtt"]["base_topic"],
            static_config["hostname"]["name"],
            static_config["mqtt"]["topic"]["set"],
            "report_interval",
        ),
    )
    payload = "[" * 100_000 + "]" * 100_000

    with (
        patch(
            "redreactor.components.commander.commander.COMMAND_PAYLOAD_MAXIMUM",
            len(payload),
        ),
        patch.object(cmd.logger, "warning") as mock_warn,
    ):
        cmd._on_message(None, None, _make_mock_message(topic, payload))

    assert "not valid JSON" in mock_warn.call_args.args[0]


def test_on_command_unsplittable_command_still_disconnects(commander, static_config):
    """A command shlex can't split is logged, and the service still exits.

    The readings are already stopped by then, so carrying on would leave the
    service running but doing nothing.
    """
    cmd, _ = commander
    from redreactor.components.mqtt import MQTT

    static_config["system"]["shutdown"] = "echo 'unbalanced"
    MQTT.event.on("publish", lambda **_: None)
    disconnect_calls: list[bool] = []
    MQTT.event.on("disconnect", lambda: disconnect_calls.append(True))

    with patch("time.sleep"), patch.object(cmd.logger, "exception") as mock_exc:
        cmd._on_command("shutdown")

    mock_exc.assert_called_once()
    assert disconnect_calls == [True]


def test_on_command_hanging_command_times_out(commander):
    """A command that never finishes is given up on, then disconnects."""
    import subprocess

    from redreactor.components.mqtt import MQTT
    from redreactor.const import SYSTEM_COMMAND_TIMEOUT

    cmd, _ = commander
    MQTT.event.on("publish", lambda **_: None)
    disconnect_calls: list[bool] = []
    MQTT.event.on("disconnect", lambda: disconnect_calls.append(True))

    target = "redreactor.components.commander.commander.subprocess.run"
    with (
        patch(
            target,
            side_effect=subprocess.TimeoutExpired("sleep", SYSTEM_COMMAND_TIMEOUT),
        ) as mock_run,
        patch("time.sleep"),
        patch.object(cmd.logger, "error") as mock_error,
    ):
        cmd._on_command("restart")

    assert mock_run.call_args.kwargs["timeout"] == SYSTEM_COMMAND_TIMEOUT
    assert "did not finish" in mock_error.call_args.args[0]
    assert disconnect_calls == [True]
