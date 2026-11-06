"""Tests for the command line entry point."""

from __future__ import annotations

import json
import sys
from logging.handlers import RotatingFileHandler
from unittest.mock import patch

import pytest
import yaml

from redreactor.const import DEFAULT_LOG_BACKUP_COUNT, DEFAULT_LOG_MAX_BYTES


@pytest.fixture
def config_files(tmp_path):
    """Write a minimal config file and return the command line arguments."""
    static_file = tmp_path / "config.yaml"
    static_file.write_text(yaml.dump({"hostname": {"name": "test-pi"}}))
    return [
        "redreactor",
        "--config",
        str(static_file),
        "--database",
        str(tmp_path / "database.db"),
        "--log",
        str(tmp_path / "redreactor.log"),
    ]


@pytest.fixture(autouse=True)
def remove_log_handlers():
    """Remove the handlers main() adds to the shared logger."""
    import logging

    logger = logging.getLogger("Red Reactor")
    before = list(logger.handlers)
    yield
    for handler in logger.handlers[len(before) :]:
        handler.close()
        logger.removeHandler(handler)


def test_check_prints_reading_without_mqtt(config_files, capsys):
    """--check prints one reading and never creates the MQTT client."""
    from redreactor import __main__

    reading = {"voltage": 4.1, "current": -120.0}
    with (
        patch.object(sys, "argv", [*config_files, "--check"]),
        patch.object(__main__, "read_once", return_value=reading) as read_once,
        patch.object(__main__, "MQTT") as mqtt,
        patch.object(__main__, "Monitor") as monitor,
    ):
        __main__.main()

    read_once.assert_called_once()
    mqtt.assert_not_called()
    monitor.assert_not_called()
    assert json.loads(capsys.readouterr().out) == reading


def test_log_file_is_rotated(config_files):
    """The log file is capped so it can't fill the SD card."""
    import logging

    from redreactor import __main__

    with (
        patch.object(sys, "argv", [*config_files, "--check"]),
        patch.object(__main__, "read_once", return_value={}),
    ):
        __main__.main()

    handlers = [
        handler
        for handler in logging.getLogger("Red Reactor").handlers
        if isinstance(handler, RotatingFileHandler)
    ]
    assert handlers
    assert handlers[-1].maxBytes == DEFAULT_LOG_MAX_BYTES
    assert handlers[-1].backupCount == DEFAULT_LOG_BACKUP_COUNT


def test_invalid_configuration_exits_without_a_traceback(tmp_path, caplog):
    """A configuration problem is one clear line, then exit 1."""
    from redreactor import __main__

    static_file = tmp_path / "config.yaml"
    static_file.write_text("mqtt: {port: 0}\n")
    argv = [
        "redreactor",
        "--config",
        str(static_file),
        "--database",
        str(tmp_path / "database.db"),
        "--log",
        str(tmp_path / "redreactor.log"),
    ]

    with patch.object(sys, "argv", argv), pytest.raises(SystemExit) as exit_info:
        __main__.main()

    assert exit_info.value.code == 1
    assert "`mqtt.port`" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_log_file_that_cannot_be_opened_uses_the_console(tmp_path, caplog):
    """A log file in a missing folder doesn't stop the service starting."""
    from redreactor import __main__

    static_file = tmp_path / "config.yaml"
    static_file.write_text("")
    argv = [
        "redreactor",
        "--config",
        str(static_file),
        "--database",
        str(tmp_path / "database.db"),
        "--log",
        str(tmp_path / "missing" / "redreactor.log"),
        "--check",
    ]

    with (
        patch.object(sys, "argv", argv),
        patch.object(__main__, "read_once", return_value={}) as read_once,
    ):
        __main__.main()

    read_once.assert_called_once()
    assert "Unable to open the log file" in caplog.text
