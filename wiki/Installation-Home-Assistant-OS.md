# Installing on Home Assistant OS

Red Reactor integrates with Home Assistant via MQTT auto-discovery. If you are running Home Assistant OS (HAOS) on your Raspberry Pi, the easiest installation method is the dedicated **Red Reactor Home Assistant Add-on**, which handles everything automatically.

---

## Prerequisites

Before installing, ensure you have:

- A Raspberry Pi with a **Red Reactor** board attached
- **Home Assistant OS** running on that Raspberry Pi
- The **Mosquitto broker** add-on (or another MQTT broker) installed and running in Home Assistant
- The **MQTT integration** configured in Home Assistant (`Settings > Devices & Services > Add Integration > MQTT`)

---

## Step 1 — Add the Red Reactor Add-on Repository

1. In Home Assistant, navigate to **Settings > Add-ons > Add-on Store**
2. Click the **⋮ menu** (top right) and select **Repositories**
3. Add the following repository URL:

   ```
   https://github.com/mreditor97/homeassistant-addons
   ```

4. Click **Add**, then close the dialog
5. Refresh the page — the **Red Reactor** add-on will appear in the store

---

## Step 2 — Install the Add-on

1. Find **Red Reactor** in the add-on store and click it
2. Click **Install** and wait for the installation to complete

---

## Step 3 — Configure the Add-on

Before starting the add-on, open the **Configuration** tab and set your MQTT broker details:

```yaml
mqtt:
  broker: core-mosquitto   # Use 'core-mosquitto' for the built-in Mosquitto add-on
  port: 1883
  user: your_mqtt_username
  password: your_mqtt_password

hostname:
  name: redreactor-pi       # Used in MQTT topics, e.g. redreactor/redreactor-pi/state
  pretty: Red Reactor Pi    # Display name in Home Assistant
```

Key options:

| Option | Default | Description |
|---|---|---|
| `mqtt.broker` | `127.0.0.1` | MQTT broker hostname or IP |
| `mqtt.port` | `1883` | MQTT broker port |
| `mqtt.user` | — | MQTT username |
| `mqtt.password` | — | MQTT password |
| `hostname.name` | `redreactor` | Slug used in MQTT topics |
| `hostname.pretty` | `Red Reactor` | Friendly name shown in HA |
| `homeassistant.discovery` | `true` | Enable MQTT auto-discovery |

---

## Step 4 — Start the Add-on

1. Click **Start** on the add-on Info tab
2. Enable **Start on boot** and **Watchdog** so the service restarts automatically
3. Check the **Log** tab to confirm it connected to the MQTT broker successfully:

   ```
   INFO - Connecting to MQTT Broker at core-mosquitto:1883
   INFO - Connected to MQTT Broker
   INFO - Initiating battery monitor
   ```

---

## Step 5 — Verify in Home Assistant

With MQTT auto-discovery enabled, Home Assistant will automatically create a **Red Reactor** device with all sensors and controls:

- Navigate to **Settings > Devices & Services > MQTT**
- You should see a new **Red Reactor** device with entities for voltage, current, battery level, CPU temperature, and more
- The **Restart** and **Shutdown** buttons are also available as entities on the device

---

## Troubleshooting

**No device appears in Home Assistant**
- Confirm the MQTT integration is configured in Home Assistant
- Check the add-on log for connection errors
- Verify the MQTT broker username and password are correct

**"Unable to connect to the Red Reactor" error**
- Ensure the Red Reactor board is properly seated on the GPIO header
- Confirm I2C is enabled (the add-on enables this automatically, but check via **Settings > System > Hardware**)

**Service stops unexpectedly**
- Enable the **Watchdog** option on the add-on to restart it automatically on failure
