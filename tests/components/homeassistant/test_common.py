"""Tests for homeassistant/common.py."""

from __future__ import annotations

import json

from redreactor.components.homeassistant.common import (
    Availability,
    Device,
    Encoder,
    Representer,
)


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def test_availability_serialises_correctly():
    """Availability stores its attributes."""
    avail = Availability(
        topic="redreactor/status",
        payload_available="online",
        payload_not_available="offline",
    )
    assert avail.topic == "redreactor/status"
    assert avail.payload_available == "online"
    assert avail.payload_not_available == "offline"


def test_availability_without_optionals():
    """Availability with only required topic does not raise."""
    avail = Availability(topic="redreactor/status")
    assert avail.topic == "redreactor/status"
    assert avail.payload_available is None
    assert avail.payload_not_available is None


# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------


def test_device_serialises_correctly():
    """Device stores its attributes."""
    device = Device(
        name="Red Reactor",
        manufacturer="PiJuice",
        model="RedReactor v1",
        identifiers="redreactor-001",
    )
    assert device.name == "Red Reactor"
    assert device.manufacturer == "PiJuice"
    assert device.model == "RedReactor v1"
    assert device.identifiers == "redreactor-001"


def test_device_defaults_none():
    """Device defaults all optional fields to None."""
    device = Device()
    assert device.name is None
    assert device.manufacturer is None
    assert device.model is None


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------


def test_encoder_handles_device():
    """Encoder serialises Device objects via json.dumps."""
    device = Device(name="Test", manufacturer="Acme")
    result = json.dumps(device, cls=Encoder)
    data = json.loads(result)
    assert data["name"] == "Test"
    assert data["manufacturer"] == "Acme"


def test_encoder_handles_availability():
    """Encoder serialises Availability objects via json.dumps."""
    avail = Availability(topic="test/status", payload_available="online")
    result = json.dumps(avail, cls=Encoder)
    data = json.loads(result)
    assert data["topic"] == "test/status"
    assert data["payload_available"] == "online"
    # None values should be omitted
    assert "payload_not_available" not in data


def test_encoder_omits_none_values():
    """Encoder omits None-valued fields from JSON output."""
    device = Device(name="OnlyName")
    result = json.dumps(device, cls=Encoder)
    data = json.loads(result)
    assert "name" in data
    # All other None fields should be absent
    for key, value in data.items():
        assert value is not None


# ---------------------------------------------------------------------------
# Representer
# ---------------------------------------------------------------------------


def test_representer_repr_returns_non_empty_string():
    """Representer.__repr__ returns a non-empty string."""
    avail = Availability(topic="test/topic", payload_available="online")
    result = repr(avail)
    assert isinstance(result, str)
    assert len(result) > 0
    assert "test/topic" in result


def test_representer_repr_omits_none_values():
    """Representer.__repr__ excludes None values."""
    avail = Availability(topic="test/topic")
    result = repr(avail)
    # payload_available is None — should not appear
    assert "payload_available" not in result
