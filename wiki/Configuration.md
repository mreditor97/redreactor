# Configuration

Red Reactor is configured via a YAML file (default: `config.yaml`). A fully annotated example is available in the repository at [`extras/config.yaml`](https://github.com/mreditor97/redreactor/blob/master/extras/config.yaml).

Download it to get started:

```bash
curl -fsSL https://raw.githubusercontent.com/mreditor97/redreactor/master/extras/config.yaml \
  -o config.yaml
```

---

## MQTT

```yaml
mqtt:
  broker: 192.168.1.100   # MQTT broker IP or hostname
  port: 1883               # Default MQTT port
  user: your_username
  password: your_password
  version: 5               # Protocol version: 3 or 5
  client_id: Red Reactor
  base_topic: redreactor   # Root prefix for all MQTT topics
  transport: tcp
  timeout: 120
  exit_on_fail: true       # Exit if the broker is unreachable on startup
```

| Key | Default | Description |
|---|---|---|
| `mqtt.broker` | `127.0.0.1` | MQTT broker address |
| `mqtt.port` | `1883` | MQTT broker port |
| `mqtt.version` | `3` | Protocol version (`3` = MQTTv3.1.1, `5` = MQTTv5) |
| `mqtt.base_topic` | `redreactor` | Root topic prefix |
| `mqtt.exit_on_fail` | `true` | Exit the service if the broker is unreachable |

---

## Hostname

Controls the device name used in MQTT topics and the Home Assistant device registry.

```yaml
hostname:
  name: redreactor-pi     # Slug — used in MQTT topics, e.g. redreactor/redreactor-pi/state
  pretty: Red Reactor Pi  # Human-readable name shown in Home Assistant
```

The `name` must be unique if you are running multiple Red Reactor devices on the same broker.

---

## Home Assistant

```yaml
homeassistant:
  discovery: true           # Publish MQTT discovery messages for auto-discovery
  topic: homeassistant      # HA discovery topic prefix
  discovery_interval: 120   # Re-publish discovery config every N seconds
  expire_after: 120         # Seconds before HA marks a sensor unavailable
```

| Key | Default | Description |
|---|---|---|
| `homeassistant.discovery` | `true` | Enable MQTT auto-discovery |
| `homeassistant.topic` | `homeassistant` | HA discovery topic prefix |
| `homeassistant.discovery_interval` | `120` | Re-publish interval (seconds) |
| `homeassistant.expire_after` | `120` | Sensor expiry timeout (seconds) |

---

## System Commands

The commands sent to the OS when a shutdown or restart is triggered via MQTT.

```yaml
system:
  shutdown: sudo shutdown 0 -h
  restart: sudo shutdown 0 -r
```

On Linux/Docker, the `redreactor` user must have a sudoers rule for `/sbin/shutdown`. See the [Ubuntu / Standard Linux OS](Linux) guide for setup details.

---

## Logging

```yaml
logging:
  console: INFO     # Log level for stdout: DEBUG, INFO, WARNING, ERROR, CRITICAL
  file: WARNING     # Log level for the log file
```

---

## INA219 Sensor

These values should match your Red Reactor hardware revision. The defaults are correct for the standard Red Reactor board.

```yaml
ina:
  address: 0x40         # I2C address of the INA219
  shunt_ohms: 0.05      # Shunt resistor value
  max_expected_amps: 5.5
  monitor_interval: 5   # How often to read the sensor (seconds)
```

---

## MQTT Topics

Once running, the service publishes to the following topics (using the configured `base_topic` and `hostname.name`):

| Topic | Description |
|---|---|
| `redreactor/{name}/state` | JSON payload with all sensor readings |
| `redreactor/{name}/status` | `online` or `offline` |
| `redreactor/{name}/set/{command}` | Inbound command topic |

### State Payload

```json
{
  "voltage": 4.164,
  "current": 2.18,
  "battery_level": 100,
  "external_power": "ON",
  "cpu_temperature": 49.1,
  "cpu_stat": "OK",
  "cpu_stat_raw": 0,
  "battery_warning_threshold": 10,
  "battery_voltage_minimum": 2.9,
  "battery_voltage_maximum": 4.2,
  "report_interval": 30
}
```

### Commands

Send a JSON value to `redreactor/{name}/set/{command}`:

| Command | Type | Description |
|---|---|---|
| `battery_warning_threshold` | integer | Warn and publish immediately below this % |
| `battery_voltage_minimum` | float | Shutdown threshold voltage |
| `battery_voltage_maximum` | float | Full charge voltage |
| `report_interval` | integer | Seconds between state publishes (5–300) |
| `restart` | any | Restart the device immediately |
| `shutdown` | any | Shut the device down immediately |
