"""Tests for the shared MQTT topics and payloads."""

from __future__ import annotations

from redreactor.helpers.topics import Topics, binary_payload


def test_topics_from_configuration(static_config):
    """Each topic is the base topic, the hostname and the topic name."""
    topics = Topics.from_configuration(static_config)

    assert topics.device == "redreactor/redreactor"
    assert topics.status == "redreactor/redreactor/status"
    assert topics.state == "redreactor/redreactor/state"
    assert topics.event == "redreactor/redreactor/event"
    assert topics.command("report_interval") == (
        "redreactor/redreactor/set/report_interval"
    )


def test_topics_follow_renamed_topics(static_config):
    """Configured topic names and hostname are used everywhere."""
    static_config["mqtt"]["base_topic"] = "ups"
    static_config["hostname"]["name"] = "pluto"
    static_config["mqtt"]["topic"]["set"] = "command"
    static_config["mqtt"]["topic"]["state"] = "data"

    topics = Topics.from_configuration(static_config)

    assert topics.state == "ups/pluto/data"
    assert topics.set_prefix == "ups/pluto/command/"


def test_binary_payload_defaults():
    """Without payloads configured, ON and OFF are used."""
    assert binary_payload({}, value=True) == "ON"
    assert binary_payload({}, value=False) == "OFF"


def test_binary_payload_configured():
    """A field's own payloads are used."""
    field = {"payload_on": "yes", "payload_off": "no"}

    assert binary_payload(field, value=True) == "yes"
    assert binary_payload(field, value=False) == "no"
