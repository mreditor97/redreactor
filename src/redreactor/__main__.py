"""Red Reactor bootstrap."""

import argparse
import logging
from importlib.metadata import version

from redreactor.components.commander import Commander
from redreactor.components.homeassistant import Homeassistant
from redreactor.components.monitor import Monitor
from redreactor.components.mqtt import MQTT
from redreactor.configuration import LinkedConfiguration


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

    # Create logger, enable all msgs
    logger = logging.getLogger("Red Reactor")
    # Set to stop INA219 logging
    logger.propagate = False
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
    configuration = LinkedConfiguration(args.configuration_file, args.database_file)

    # Update logging levels, limited to listed set
    logging_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    if str(configuration.static["logging"]["console"]).upper() in logging_levels:
        c_handler.setLevel(configuration.static["logging"]["console"])
        logger.info(
            "Console log level set to %s",
            configuration.static["logging"]["console"],
        )
    if str(configuration.static["logging"]["file"]).upper() in logging_levels:
        f_handler.setLevel(configuration.static["logging"]["file"])
        logger.info(
            "File log level set to %s",
            configuration.static["logging"]["file"],
        )

    # Setup MQTT Connection
    mqtt = MQTT(
        configuration.static,
        exit_on_fail=bool(configuration.static["mqtt"]["exit_on_fail"]),
    )

    # Setup INA216 Battery Monitoring
    monitor = Monitor(configuration.static, configuration.dynamic)

    # Setup MQTT Commander and Battery Shutdown / Reboot commands
    Commander(configuration.static, configuration.dynamic, monitor)

    # Create Home Assistant data if enabled
    if bool(configuration.static["homeassistant"]["discovery"]):
        Homeassistant(configuration.static, configuration.dynamic)

    # Connect to MQTT server and loop forever
    mqtt.connect(
        configuration.static["mqtt"]["broker"],
        int(configuration.static["mqtt"]["port"]),
        int(configuration.static["mqtt"]["timeout"]),
    )


if __name__ == "__main__":
    main()
