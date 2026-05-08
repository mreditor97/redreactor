# Docker

This guide covers running Red Reactor as a Docker container. The container accesses the host's I2C bus to communicate with the INA219 sensor on the Red Reactor board.

---

## Prerequisites

- A Raspberry Pi with a **Red Reactor** board attached
- Docker and Docker Compose installed on the host
- An accessible MQTT broker
- I2C enabled on the host OS — follow **Step 1** of the [Ubuntu / Standard Linux OS](Linux) guide, then return here

---

## Step 1 — Create the Configuration File

Create a working directory and config file:

```bash
mkdir -p ~/redreactor
```

Create `~/redreactor/config.yaml` — see the [configuration reference](Linux#step-5--configure-red-reactor) in the Linux guide for all available options. At minimum:

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

## Step 2 — Create a Dockerfile

Create `~/redreactor/Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir redreactor

ENTRYPOINT ["python", "-m", "redreactor"]
CMD ["--config=/config/config.yaml", "--database=/data/database.db", "--log=/data/redreactor.log"]
```

---

## Step 3 — Docker Compose

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

> **Note on `privileged: true`**: Only needed if you use the MQTT shutdown or restart commands. If not, replace it with the narrower capability:
> ```yaml
>     cap_add:
>       - SYS_BOOT
> ```

---

## Step 4 — Build and Start

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

## Step 5 — Verify in Home Assistant

If `homeassistant.discovery: true` is set and Home Assistant is on the same MQTT broker, the Red Reactor device appears automatically under **Settings > Devices & Services > MQTT**.

---

## Updating

```bash
cd ~/redreactor
docker compose up -d --build --pull always
```

---

## Troubleshooting

**"Unable to connect to the Red Reactor" on startup**
- Confirm `/dev/i2c-1` exists: `ls /dev/i2c-*`
- Confirm the `devices` mapping in `docker-compose.yaml` includes `/dev/i2c-1`
- Confirm I2C is enabled on the host: `i2cdetect -y 1` should show `40`

**Container exits immediately**
- Check logs: `docker compose logs redreactor`
- If `exit_on_fail: true`, an MQTT connection failure exits the container — verify broker address and credentials
- The `restart: unless-stopped` policy will restart it automatically

**Shutdown/restart commands have no effect**
- The container needs `privileged: true` or `cap_add: [SYS_BOOT]` to signal the host
- Verify: `docker exec redreactor which shutdown`

If you have problems, create an [issue](https://github.com/mreditor97/redreactor/issues) on the GitHub repository.
