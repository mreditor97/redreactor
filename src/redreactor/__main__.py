"""Red Reactor bootstrap."""

import argparse
import json
import logging
import sys
from importlib.metadata import version
from logging.handlers import RotatingFileHandler
from typing import Any

from redreactor.components.commander import Commander
from redreactor.components.homeassistant import Homeassistant
from redreactor.components.monitor import Monitor, read_once
from redreactor.components.mqtt import MQTT
from redreactor.configuration import ConfigurationError, LinkedConfiguration
from redreactor.const import DEFAULT_LOG_BACKUP_COUNT, DEFAULT_LOG_MAX_BYTES
from redreactor.helpers.systemd import notify, start_watchdog


def get_arguments() -> argparse.Namespace:
    """Get passed arguments parsed."""
    parser = argparse.ArgumentParser(description="Red Reactor MQTT Client")
    parser.add_argument(
        "-c",
        "--config",
        default="config.yaml",
        help="Configuration file, defaults to `config.yaml`",
        dest="configuration_file",
    )
    parser.add_argument(
        "-d",
        "--database",
        default="database.db",
        help="Database for storing latest dynamic configuration options",
        dest="database_file",
    )
    parser.add_argument(
        "-l",
        "--log",
        default="redreactor.log",
        help="Logging file location",
        dest="logging_file",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Read the Red Reactor once, print the result and exit without "
        "connecting to MQTT. Useful for checking the I2C setup",
        dest="check",
    )

    return parser.parse_args()


def _set_log_levels(
    logging_configuration: dict[str, Any],
    handlers: tuple[tuple[str, logging.Handler | None], ...],
) -> None:
    """Set each log handler's level from the configuration.

    Limited to the listed levels. Handler.setLevel() only accepts upper case
    names, so they are normalised first.
    """
    logger = logging.getLogger("Red Reactor")
    logging_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    for name, handler in handlers:
        if handler is None:
            continue
        level = str(logging_configuration[name]).upper()
        if level in logging_levels:
            handler.setLevel(level)
            logger.info("%s log level set to %s", name.capitalize(), level)
        else:
            logger.warning(
                "Invalid %s log level %r, must be one of %s",
                name,
                logging_configuration[name],
                ", ".join(logging_levels),
            )


def _notify_systemd(monitor: Monitor) -> None:
    """Tell systemd the service has started, and start its watchdog pings.

    Under systemd with `Type=notify`, the service counts as started from here,
    and the watchdog restarts it if the readings stop. Outside systemd neither
    does anything.
    """
    notify("READY=1")
    start_watchdog(monitor.is_healthy)


def main() -> None:
    """Start Red Reactor Battery Monitor service."""
    args = get_arguments()

    logger = logging.getLogger("Red Reactor")
    # Keep our messages to our own handlers, rather than also passing them up
    # to any root logger a library sets up.
    logger.propagate = False
    # Root level is INFO so all handlers receive every message; each handler
    # then applies its own level from the config file (set below).
    logger.setLevel(logging.INFO)

    # Create handlers
    c_handler = logging.StreamHandler()
    f_handler: logging.Handler | None
    try:
        f_handler = RotatingFileHandler(
            args.logging_file,
            maxBytes=DEFAULT_LOG_MAX_BYTES,
            backupCount=DEFAULT_LOG_BACKUP_COUNT,
        )
    except OSError as error:
        # The battery monitoring matters more than the log file, so carry on
        # with the console log only
        f_handler = None
        log_file_error: OSError | None = error
    else:
        log_file_error = None

    # Create formatters and add it to handlers
    c_format = logging.Formatter(
        "%(asctime)s - %(filename)s - %(levelname)s - %(message)s",
    )
    f_format = logging.Formatter(
        "%(asctime)s - %(filename)s - %(levelname)s - %(message)s",
        datefmt="%d-%b-%y %H:%M:%S",
    )
    c_handler.setFormatter(c_format)
    logger.addHandler(c_handler)
    if f_handler is not None:
        f_handler.setFormatter(f_format)
        logger.addHandler(f_handler)
    else:
        logger.warning(
            "Unable to open the log file %s (%s), logging to the console only",
            args.logging_file,
            log_file_error,
        )

    logger.info("#########################################")
    logger.info("#### Red Reactor MQTT Client (%s) ####", version("redreactor"))
    logger.info("# With MQTT, and Home Assistant Support #")
    logger.info("Loading in static configuration file: %s", args.configuration_file)
    logger.info("Loading in dynamic configuration file: %s", args.database_file)

    # Load in configuration files
    try:
        configuration = LinkedConfiguration(
            args.configuration_file,
            args.database_file,
        )
    except ConfigurationError as error:
        # The message names the problem, a traceback would only bury it
        logger.error(  # noqa: TRY400
            "Unable to start with the current configuration: %s",
            error,
        )
        sys.exit(1)

    _set_log_levels(
        configuration.static["logging"],
        (("console", c_handler), ("file", f_handler)),
    )

    if args.check:
        print(json.dumps(read_once(configuration.static), indent=2))  # noqa: T201
        return

    # Components register their callbacks on MQTT.event during __init__, so
    # they must all be constructed before mqtt.connect() is called.
    mqtt = MQTT(
        configuration.static,
        exit_on_fail=bool(configuration.static["mqtt"]["exit_on_fail"]),
    )

    # Setup INA219 Battery Monitoring
    monitor = Monitor(configuration.static, configuration.dynamic)

    # Commander subscribes to MQTT set-topics and wires up shutdown/restart.
    Commander(configuration.static, configuration.dynamic, monitor)

    if bool(configuration.static["homeassistant"]["discovery"]):
        Homeassistant(configuration.static, configuration.dynamic)

    _notify_systemd(monitor)

    # Blocks here — loop_forever() drives the entire application until the
    # battery shuts the device down or the process is signalled.
    mqtt.connect(
        configuration.static["mqtt"]["broker"],
        int(configuration.static["mqtt"]["port"]),
        int(configuration.static["mqtt"]["timeout"]),
    )


if __name__ == "__main__":
    main()
