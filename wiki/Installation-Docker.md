# Installing via Docker

This guide covers running Red Reactor as a Docker container. The container needs access to the I2C bus on the host to communicate with the INA219 sensor on the Red Reactor board.

---

## Prerequisites

- A Raspberry Pi with a **Red Reactor** board attached
- Docker and Docker Compose installed on the host
- An accessible MQTT broker
- I2C enabled on the host OS (see below)

---

## Step 1 — Enable I2C on the Host

Even when running inside Docker, the container uses the host's I2C device. Enable I2C on the Pi:

```bash
sudo raspi-config
```

Navigate to **Interface Options > I2C > Enable**, then reboot.

Verify the INA219 is visible at address `0x40`:

```bash
sudo apt install -y i2c-tools
i2cdetect -y 1
```

---

## Step 2 — Create the Configuration File

Create a directory for your configuration:

```bash
mkdir -p ~/redreactor
```

Create `~/redreactor/config.yaml` with your MQTT settings:

```yaml
---
mqtt:
  broker: 192.168.1.100   # Your MQTT broker IP or hostname
  port: 1883
  user: your_mqtt_username
  password: your_mqtt_password
  version: 5

  client_id: Red Reactor
  base_topic: redreactor

  exit_on_fail: true

hostname:
  name: redreactor-pi     # Slug used in MQTT topics
  pretty: Red Reactor Pi  # Friendly display name

homeassistant:
  discovery: true
  topic: homeassistant
  discovery_interval: 120
  expire_after: 120

system:
  shutdown: sudo shutdown 0 -h
  restart: sudo shutdown 0 -r

logging:
  console: INFO
  file: WARNING
```

---

## Step 3 — Create a Dockerfile

Create `~/redreactor/Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir redreactor

ENTRYPOINT ["python", "-m", "redreactor"]
CMD ["--config=/config/config.yaml", "--database=/data/database.db", "--log=/data/redreactor.log"]
```

---

## Step 4 — Docker Compose (Recommended)

Create `~/redreactor/docker-compose.yaml`:

```yaml
services:
  redreactor:
    build: .
    container_name: redreactor
    restart: unless-stopped

    # Required: pass the I2C bus into the container
    devices:
      - /dev/i2c-1:/dev/i2c-1

    volumes:
      # Mount config file (read-only)
      - ./config.yaml:/config/config.yaml:ro
      # Persist the dynamic settings database and log file
      - redreactor-data:/data

    # Required for shutdown/restart commands to affect the host
    privileged: true

volumes:
  redreactor-data:
```

> **Note on `privileged: true`**: This is required only if you use the MQTT shutdown or restart commands, since the container must be able to signal the host via `sudo shutdown`. If you do not need remote shutdown/restart, replace `privileged: true` with the narrower capability:
> ```yaml
>     cap_add:
>       - SYS_BOOT
> ```

---

## Step 5 — Build and Start

```bash
cd ~/redreactor
docker compose up -d --build
```

View logs:

```bash
docker compose logs -f redreactor
```

Expected output:

```
INFO - Connecting to MQTT Broker at 192.168.1.100:1883
INFO - Connected to MQTT Broker
INFO - Initiating battery monitor
INFO - Home Assistant support has been enabled
```

---

## Step 6 — Verify in Home Assistant

If `homeassistant.discovery: true` is set and Home Assistant is connected to the same MQTT broker, the Red Reactor device will be auto-discovered automatically under **Settings > Devices & Services > MQTT**.

---

## Updating

Pull the latest image and rebuild:

```bash
cd ~/redreactor
docker compose pull
docker compose up -d --build
```

Or, if using a published image rather than a local build:

```bash
docker compose pull && docker compose up -d
```

---

## Configuration Reference

The container accepts three CLI flags via the `CMD` directive:

| Flag | Default | Description |
|---|---|---|
| `--config` | `config.yaml` | Path to the YAML configuration file |
| `--database` | `database.db` | Path to the dynamic settings JSON database |
| `--log` | `redreactor.log` | Path to the log file |

---

## Troubleshooting

**"Unable to connect to the Red Reactor" on startup**
- Confirm `/dev/i2c-1` exists on the host: `ls /dev/i2c-*`
- Confirm I2C is enabled: `i2cdetect -y 1` should show `40` in the grid
- Confirm the `devices` mapping in `docker-compose.yaml` includes `/dev/i2c-1`

**Container exits immediately**
- Check logs: `docker compose logs redreactor`
- If `exit_on_fail: true`, an MQTT connection failure will exit the container — verify broker address and credentials
- The compose `restart: unless-stopped` policy will restart it automatically

**Shutdown/restart commands have no effect**
- The container must be run with `privileged: true` or `cap_add: [SYS_BOOT]` for `shutdown` to propagate to the host
- Verify the host's `shutdown` binary is accessible inside the container: `docker exec redreactor which shutdown`
