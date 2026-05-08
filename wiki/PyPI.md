# Installing via PyPI

Red Reactor is published on [PyPI](https://pypi.org/project/redreactor/) and can be installed directly with `pip`. This is the quickest approach if you already have a Python environment on your Raspberry Pi and want to run the service manually or integrate it into an existing setup.

For a fully managed installation (auto-start on boot, dedicated user), see the [Ubuntu / Standard Linux OS](Linux) guide instead — it uses PyPI under the hood.

---

## Prerequisites

- A Raspberry Pi with a **Red Reactor** board attached
- I2C enabled — follow **Step 1** of the [Ubuntu / Standard Linux OS](Linux) guide
- Python 3.10 or later
- An accessible MQTT broker

---

## Install

```bash
python3 -m venv redreactor-venv
source redreactor-venv/bin/activate
pip install redreactor
```

Verify:

```bash
python -m redreactor --help
```

---

## Configure

Download the example config and edit it:

```bash
curl -fsSL https://raw.githubusercontent.com/mreditor97/redreactor/master/extras/config.yaml \
  -o config.yaml
nano config.yaml
```

See the [configuration reference](Linux#step-5--configure-red-reactor) in the Linux guide for all available keys. At minimum:

```yaml
mqtt:
  broker: 192.168.1.100
  port: 1883
  user: your_mqtt_username
  password: your_mqtt_password

hostname:
  name: redreactor-pi
  pretty: Red Reactor Pi
```

---

## Run

```bash
python -m redreactor --config config.yaml --database database.db --log redreactor.log
```

| Flag | Default | Description |
|---|---|---|
| `--config` | `config.yaml` | YAML configuration file |
| `--database` | `database.db` | Dynamic settings database |
| `--log` | `redreactor.log` | Log file path |

---

## Update

```bash
pip install --upgrade redreactor
```

To pin a specific version:

```bash
pip install redreactor==0.1.7
```

See the [releases page](https://github.com/mreditor97/redreactor/releases) for changelogs.

---

## Run as a Service

Once verified, follow the [Ubuntu / Standard Linux OS](Linux) guide to configure it as a systemd service that starts automatically on boot.
