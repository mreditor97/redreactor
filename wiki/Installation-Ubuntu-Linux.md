# Installing on Ubuntu / Standard Linux

This guide covers installing Red Reactor as a persistent background service on Ubuntu or any standard Debian-based Linux distribution running on a Raspberry Pi.

---

## Prerequisites

- A Raspberry Pi with a **Red Reactor** board attached
- Ubuntu 22.04+ (or equivalent Debian-based distro) — Python 3.10 or later required
- An accessible MQTT broker (e.g. Mosquitto running locally or on your Home Assistant instance)
- Root / `sudo` access

---

## Step 1 — Enable I2C

The Red Reactor uses I2C to communicate with the INA219 power monitor. Enable I2C on your Pi:

```bash
sudo raspi-config
```

Navigate to **Interface Options > I2C > Enable**, then reboot.

Verify the INA219 is detected (default address `0x40`):

```bash
sudo apt install -y i2c-tools
i2cdetect -y 1
```

You should see `40` in the output grid.

---

## Step 2 — Install Python 3.10+

```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv
python3 --version   # must be 3.10 or later
```

---

## Step 3 — Create a Dedicated User and Directories

Running as a dedicated user limits the service's permissions:

```bash
# Create user without a login shell
sudo useradd --system --no-create-home --shell /usr/sbin/nologin redreactor

# Working directory (holds the virtualenv and dynamic database)
sudo mkdir -p /var/lib/redreactor

# Configuration directory
sudo mkdir -p /etc/redreactor

# Set ownership
sudo chown redreactor:redreactor /var/lib/redreactor /etc/redreactor
```

---

## Step 4 — Install Red Reactor into a Virtualenv

```bash
# Create the virtualenv
sudo -u redreactor python3 -m venv /var/lib/redreactor/.venv

# Install Red Reactor from PyPI
sudo -u redreactor /var/lib/redreactor/.venv/bin/pip install redreactor
```

---

## Step 5 — Configure Red Reactor

Copy the example configuration and edit it for your environment:

```bash
sudo curl -fsSL https://raw.githubusercontent.com/mreditor97/redreactor/master/extras/config.yaml \
  -o /etc/redreactor/config.yaml
sudo chown redreactor:redreactor /etc/redreactor/config.yaml
sudo nano /etc/redreactor/config.yaml
```

At minimum, update the MQTT section to point at your broker:

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

Full configuration reference:

| Key | Default | Description |
|---|---|---|
| `mqtt.broker` | `127.0.0.1` | MQTT broker address |
| `mqtt.port` | `1883` | MQTT broker port |
| `mqtt.version` | `3` | MQTT protocol version (`3` or `5`) |
| `mqtt.base_topic` | `redreactor` | Root topic prefix |
| `hostname.name` | `redreactor` | Used in MQTT topic paths |
| `homeassistant.discovery` | `true` | Enable HA MQTT auto-discovery |
| `homeassistant.expire_after` | `120` | Seconds before HA marks sensor unavailable |
| `logging.console` | `INFO` | Console log level |
| `logging.file` | `WARNING` | File log level |

---

## Step 6 — Allow Shutdown and Restart Commands

The service needs permission to call `sudo shutdown` when instructed via MQTT. Add a targeted sudoers rule:

```bash
sudo visudo -f /etc/sudoers.d/redreactor
```

Add the following line:

```
redreactor ALL=(ALL) NOPASSWD: /sbin/shutdown
```

---

## Step 7 — Install the systemd Service

```bash
sudo curl -fsSL https://raw.githubusercontent.com/mreditor97/redreactor/master/extras/redreactor.service \
  -o /etc/systemd/system/redreactor.service

sudo systemctl daemon-reload
sudo systemctl enable redreactor
sudo systemctl start redreactor
```

---

## Step 8 — Verify the Service

Check that the service started successfully:

```bash
sudo systemctl status redreactor
```

Expected output:

```
● redreactor.service - Red Reactor Service
     Loaded: loaded (/etc/systemd/system/redreactor.service; enabled)
     Active: active (running)
```

View live logs:

```bash
sudo journalctl -u redreactor -f
```

Or check the log file directly:

```bash
tail -f /etc/redreactor/redreactor.log
```

---

## Updating

To update to a new release:

```bash
sudo -u redreactor /var/lib/redreactor/.venv/bin/pip install --upgrade redreactor
sudo systemctl restart redreactor
```

---

## Troubleshooting

**"Unable to connect to the Red Reactor" on startup**
- Run `i2cdetect -y 1` and confirm address `0x40` is listed
- Ensure the Red Reactor board is firmly seated on the GPIO header
- Verify I2C is enabled via `raspi-config`

**Service fails to connect to MQTT**
- Test the broker manually: `mosquitto_sub -h <broker_ip> -u <user> -P <pass> -t "#" -v`
- Check the broker address, port, and credentials in `config.yaml`
- If `exit_on_fail: true`, the service exits on connection failure — check `journalctl -u redreactor` for the error

**Permission denied on shutdown**
- Verify the sudoers rule: `sudo -u redreactor sudo shutdown --help` should not prompt for a password
