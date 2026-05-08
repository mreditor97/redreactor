# Installing via PyPI

Red Reactor is published on [PyPI](https://pypi.org/project/redreactor/) and can be installed directly with `pip`. This is the quickest approach if you already have a Python environment on your Raspberry Pi and just want to run the service manually or integrate it into an existing setup.

For a fully managed installation (auto-start on boot, dedicated user, log rotation), see the [Ubuntu / Standard Linux OS](Linux) guide instead — it uses PyPI under the hood via `pip`.

---

## Prerequisites

- A Raspberry Pi with a **Red Reactor** board attached
- I2C enabled (run `sudo raspi-config` → Interface Options → I2C → Enable, then reboot)
- Python 3.10 or later
- An accessible MQTT broker

---

## Install

Create a virtual environment and install the package:

```bash
python3 -m venv redreactor-venv
source redreactor-venv/bin/activate
pip install redreactor
```

Or install into an existing virtualenv:

```bash
pip install redreactor
```

Verify the installation:

```bash
python -m redreactor --help
```

---

## Configure

Download the example configuration file and edit it for your environment:

```bash
curl -fsSL https://raw.githubusercontent.com/mreditor97/redreactor/master/extras/config.yaml \
  -o config.yaml
nano config.yaml
```

At minimum, set your MQTT broker details and hostname:

```yaml
mqtt:
  broker: 192.168.1.100   # Your MQTT broker IP or hostname
  port: 1883
  user: your_mqtt_username
  password: your_mqtt_password

hostname:
  name: redreactor-pi     # Slug used in MQTT topics
  pretty: Red Reactor Pi  # Friendly display name
```

---

## Run

```bash
python -m redreactor --config config.yaml --database database.db --log redreactor.log
```

| Flag | Default | Description |
|---|---|---|
| `--config` | `config.yaml` | Path to the YAML configuration file |
| `--database` | `database.db` | Path to the dynamic settings database |
| `--log` | `redreactor.log` | Path to the log file |

---

## Update

To update to the latest release:

```bash
pip install --upgrade redreactor
```

To update to a specific version:

```bash
pip install redreactor==0.1.7
```

Check the [releases page](https://github.com/mreditor97/redreactor/releases) for changelogs.

---

## Run as a Service

Once you have verified it works, follow the [Ubuntu / Standard Linux OS](Linux) guide to set it up as a systemd service that starts automatically on boot.
