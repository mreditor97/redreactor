"""Tests for the MQTT component."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from redreactor.helpers.emitter import EventEmitter

CLIENT = "redreactor.components.mqtt.mqtt.Client"


@pytest.fixture(autouse=True)
def reset_mqtt_events():
    """Reset the class-level MQTT EventEmitter before and after each test."""
    from redreactor.components.mqtt import MQTT

    MQTT.event = EventEmitter()
    yield
    MQTT.event = EventEmitter()


def _make_mqtt(static_config, exit_on_fail: bool = True):
    from redreactor.components.mqtt import MQTT

    with patch(CLIENT) as mock_client_class:
        mqtt = MQTT(static_config, exit_on_fail=exit_on_fail)

    return mqtt, mock_client_class.return_value


def test_last_will_is_set_before_the_first_connect(static_config):
    """The Last Will must be in the first CONNECT packet, not only on reconnects."""
    mqtt, client = _make_mqtt(static_config)

    mqtt.connect("127.0.0.1", 1883, 60)

    names = [name for name, _, _ in client.mock_calls]
    assert "will_set" in names
    assert names.index("will_set") < names.index("connect")
    client.will_set.assert_called_once_with(
        topic="redreactor/redreactor/status",
        payload="offline",
        qos=1,
        retain=True,
    )


def test_on_connect_publishes_retained_online_status(static_config):
    """Connecting replaces any retained offline status straight away."""
    mqtt, client = _make_mqtt(static_config)

    mqtt._mqtt_on_connect(client, None, None, 0)

    client.publish.assert_called_once_with(
        topic="redreactor/redreactor/status",
        payload="online",
        qos=1,
        retain=True,
    )


def test_publish_event_passes_qos_and_retain(static_config):
    """The publish event forwards qos and retain to paho."""
    from redreactor.components.mqtt import MQTT

    _, client = _make_mqtt(static_config)

    MQTT.event.emit("publish", topic="a/b", payload="x", qos=1, retain=True)

    client.publish.assert_called_once_with(
        topic="a/b",
        payload="x",
        qos=1,
        retain=True,
    )


def test_disconnect_event_disconnects_client(static_config):
    """The disconnect event ends the paho loop by disconnecting."""
    from redreactor.components.mqtt import MQTT

    _, client = _make_mqtt(static_config)

    MQTT.event.emit("disconnect")

    client.disconnect.assert_called_once_with()


@pytest.mark.parametrize(
    "error",
    [ConnectionRefusedError(), TimeoutError(), OSError("Network is unreachable")],
)
def test_connect_failure_exits_non_zero(static_config, error):
    """A failed connect exits with 1 so systemd's Restart=on-failure retries."""
    mqtt, client = _make_mqtt(static_config, exit_on_fail=True)
    client.connect.side_effect = error

    with pytest.raises(SystemExit) as exit_info:
        mqtt.connect("127.0.0.1", 1883, 60)

    assert exit_info.value.code == 1
    client.loop_forever.assert_not_called()


def test_connect_failure_retries_when_exit_on_fail_disabled(static_config):
    """With exit_on_fail disabled, paho is told to keep retrying the first connect."""
    mqtt, client = _make_mqtt(static_config, exit_on_fail=False)
    client.connect.side_effect = ConnectionRefusedError()

    mqtt.connect("127.0.0.1", 1883, 60)

    assert client.loop_forever.call_args == call(retry_first_connection=True)


def test_connect_success_runs_loop_forever(static_config):
    """A successful connect hands control to paho's loop_forever."""
    mqtt, client = _make_mqtt(static_config, exit_on_fail=True)
    client.connect.return_value = MagicMock()

    mqtt.connect("127.0.0.1", 1883, 60)

    client.loop_forever.assert_called_once_with(retry_first_connection=False)


def test_on_connect_reaches_real_listeners(static_config, dynamic_config, mock_ina):
    """Every component's on_connect listener accepts what MQTT passes it.

    The listeners name their parameters `_client`, `_userdata`, ..., so the
    event must not be emitted with keyword arguments.
    """
    from redreactor.components.commander import Commander
    from redreactor.components.homeassistant import Homeassistant
    from redreactor.components.monitor import Monitor

    mqtt, client = _make_mqtt(static_config)
    with patch(
        "redreactor.components.monitor.monitor.INA219",
        return_value=mock_ina,
    ):
        monitor = Monitor(static_config, dynamic_config)
    monitor.monitor_timer.stop()
    Commander(static_config, dynamic_config, monitor)
    homeassistant = Homeassistant(static_config, dynamic_config)

    with patch.object(monitor.report_timer, "start") as report_start, patch.object(
        homeassistant.configuration_report_timer,
        "start",
    ) as discovery_start:
        mqtt._mqtt_on_connect(client, None, None, 0)

    report_start.assert_called_once()
    discovery_start.assert_called_once()
    client.subscribe.assert_called()


def test_on_message_reaches_commander(static_config, dynamic_config):
    """A message received by MQTT reaches the Commander listener."""
    from redreactor.components.commander import Commander

    mqtt, client = _make_mqtt(static_config)
    Commander(static_config, dynamic_config, MagicMock())
    message = MagicMock()
    message.topic = "redreactor/redreactor/set/report_interval"
    message.payload = b"60"

    mqtt._mqtt_on_message(client, None, message)

    assert dynamic_config.data["report_interval"] == 60
