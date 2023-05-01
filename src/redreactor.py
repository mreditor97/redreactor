import argparse
import logging

from mqtt.mqtt import MQTT
from homeassistant.homeassistant import Homeassistant
from configuration import LinkedConfiguration
from commander import Commander
from monitor.monitor import Monitor

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
args = parser.parse_args()


def main():
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
        "%(name)s - %(filename)s - %(levelname)s - %(message)s"
    )
    f_format = logging.Formatter(
        "%(asctime)s - %(filename)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%d-%b-%y %H:%M:%S",
    )
    c_handler.setFormatter(c_format)
    f_handler.setFormatter(f_format)

    # Add handlers to the logger
    logger.addHandler(c_handler)
    logger.addHandler(f_handler)

    logger.info("###############################")
    logger.info("### Red Reactor MQTT Client ###")
    logger.info("##### With Home Assistant #####")
    logger.info(f"Loading in static configuration file: {args.configuration_file}")
    logger.info(f"Loading in dynamic configuration file: {args.database_file}")

    # Load in configuration files
    configuration = LinkedConfiguration(args.configuration_file, args.database_file)

    # Update logging levels, limited to listed set
    logging_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    if configuration.static["logging"]["console"] in logging_levels:
        c_handler.setLevel(configuration.static["logging"]["console"])
        logger.info(
            f"Console log level set to {configuration.static['logging']['console']}"
        )
    if configuration.static["logging"]["file"] in logging_levels:
        f_handler.setLevel(configuration.static["logging"]["file"])
        logger.info(f"File log level set to {configuration.static['logging']['file']}")

    # Setup MQTT Connection
    mqtt = MQTT(
        configuration.static,
        exit_on_fail=bool(configuration.static["mqtt"]["exit_on_fail"]),
    )

    # Setup INA216 Battery Monitoring
    monitor = Monitor(configuration.static, configuration.dynamic)

    # Setup MQTT Commander and Battery Shutdown / Reboot commands
    commander = Commander(configuration.static, configuration.dynamic, monitor)

    # Create Home Assistant data if enabled
    if bool(configuration.static["homeassistant"]["discovery"]):
        homeassistant = Homeassistant(configuration.static, configuration.dynamic)

    # Connect to MQTT server and loop forever
    mqtt.connect(
        configuration.static["mqtt"]["broker"],
        int(configuration.static["mqtt"]["port"]),
        int(configuration.static["mqtt"]["timeout"]),
    )


if __name__ == "__main__":
    main()
