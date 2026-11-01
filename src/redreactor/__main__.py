"""Red Reactor bootstrap."""

import argparse
import logging
import sys
from importlib.metadata import version

from redreactor.components.commander import Commander
from redreactor.components.homeassistant import Homeassistant
from redreactor.components.monitor import Monitor
from redreactor.components.mqtt import MQTT
from redreactor.configuration import ConfigurationError, LinkedConfiguration


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

    return parser.parse_args()


def main() -> None:
    """Start Red Reactor Battery Monitor service."""
    args = get_arguments()

    logger = logging.getLogger("Red Reactor")
    # Prevent INA219's internal logger (which shares the root logger) from
    # duplicating our messages up the hierarchy.
    logger.propagate = False
    # Root level is INFO so all handlers receive every message; each handler
    # then applies its own level from the config file (set below).
    logger.setLevel(logging.INFO)

    # Create handlers
    c_handler = logging.StreamHandler()
    f_handler = logging.FileHandler(args.logging_file)

    # Create formatters and add it to handlers
    c_format = logging.Formatter(
        "%(asctime)s - %(filename)s - %(levelname)s - %(message)s",
    )
    f_format = logging.Formatter(
        "%(asctime)s - %(filename)s - %(levelname)s - %(message)s",
        datefmt="%d-%b-%y %H:%M:%S",
    )
    c_handler.setFormatter(c_format)
    f_handler.setFormatter(f_format)

    # Add handlers to the logger
    logger.addHandler(c_handler)
    logger.addHandler(f_handler)

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
    except ConfigurationError:
        logger.exception("Unable to start with the current configuration")
        sys.exit(1)

    # Update logging levels, limited to listed set. Handler.setLevel() only
    # accepts upper case names, so normalise them first.
    logging_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    for handler, name in ((c_handler, "console"), (f_handler, "file")):
        level = str(configuration.static["logging"][name]).upper()
        if level in logging_levels:
            handler.setLevel(level)
            logger.info("%s log level set to %s", name.capitalize(), level)
        else:
            logger.warning(
                "Invalid %s log level %r, must be one of %s",
                name,
                configuration.static["logging"][name],
                ", ".join(logging_levels),
            )

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

    # Blocks here — loop_forever() drives the entire application until the
    # battery shuts the device down or the process is signalled.
    mqtt.connect(
        configuration.static["mqtt"]["broker"],
        int(configuration.static["mqtt"]["port"]),
        int(configuration.static["mqtt"]["timeout"]),
    )


if __name__ == "__main__":
    main()
