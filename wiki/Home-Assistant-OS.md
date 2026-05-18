# Home Assistant OS

This guide assumes you already have a working instance of Home Assistant OS. If not, follow the device installation guide on the [Home Assistant website](https://www.home-assistant.io/installation).

This example uses a Raspberry Pi with a Red Reactor UPS attached, and assumes you already have an [MQTT broker set up](https://www.home-assistant.io/integrations/mqtt/) on your instance.

---

## Prerequisites

- A Raspberry Pi with a **Red Reactor** board attached
- **Home Assistant OS** running on the Raspberry Pi
- The **Mosquitto broker** add-on (or another MQTT broker) installed and running
- The **MQTT integration** configured in Home Assistant (`Settings > Devices & Services > Add Integration > MQTT`)

---

## Step 1 — Enable I2C

The Red Reactor uses I2C to communicate with the INA219 power monitor chip. I2C must be enabled before the add-on will work.

There is a comprehensive guide available on the [Home Assistant website](https://www.home-assistant.io/common-tasks/os/#enable-i2c). Two methods are available:

### Method A — SD Card

1. With the SD card plugged into a PC, open the `hassos-boot` partition in your file manager
2. Create a folder called `CONFIG`, and inside it a folder called `modules`
3. Inside `modules`, create a text file called `rpi-i2c.conf` containing:
   ```
   i2c-dev
   ```
4. Edit `config.txt` in the root of the `hassos-boot` partition and add:
   ```
   dtparam=i2c_vc=on
   dtparam=i2c_arm=on
   ```
5. Eject, reinsert, and boot the Pi — then reboot once more to fully activate I2C

### Method B — HassOS I2C Configurator Add-on

1. Go to **Settings > Add-ons > Add-on Store > ⋮ > Repositories** and add:
   ```
   https://github.com/adamoutler/HassOSConfigurator
   ```
2. Install the **HassOS I2C Configurator** add-on
3. Disable **Protection Mode** (required)
4. Start the add-on and follow the log instructions
5. Reboot when prompted, run the add-on again, then reboot one final time
6. Uninstall the add-on and remove the repository when done

---

## Step 2 — Enable Console on tty1

The Red Reactor add-on requires a TTY console to issue shutdown and restart commands to the host. This must be set in `cmdline.txt` on the SD card.

1. Shut down the Pi and remove the SD card
2. Plug the SD card into a PC and open the `hassos-boot` partition
3. Open `cmdline.txt` and verify `console=tty1` is present on the existing line
4. If it is missing, add it — the file must remain a **single line**, e.g.:
   ```
   console=tty1 ... quiet systemd.unified_cgroup_hierarchy=false
   ```
5. Save the file, eject the card, reinsert, and boot the Pi

---

## Step 3 — Add the Red Reactor Add-on Repository

1. Go to **Settings > Add-ons > Add-on Store > ⋮ > Repositories** and add:
   ```
   https://github.com/mreditor97/homeassistant-addons
   ```
2. Click **Add**, then close the dialog
3. Refresh the page — the **Red Reactor Battery Monitor** add-on will appear in the store

---

## Step 4 — Install the Add-on

1. Find **Red Reactor Battery Monitor** in the add-on store and click it
2. Click **Install** and wait for the installation to complete

---

## Step 5 — Configure the Add-on

Open the **Configuration** tab and set your MQTT broker and hostname:

```yaml
mqtt:
  broker: core-mosquitto   # Use 'core-mosquitto' for the built-in Mosquitto add-on
  port: 1883
  user: your_mqtt_username
  password: your_mqtt_password

hostname:
  name: pi                 # Must be unique — used in MQTT topics
  pretty: Raspberry Pi     # Friendly display name in Home Assistant
```

Key configuration options:

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

## Step 6 — Start the Add-on

1. Click **Start** on the add-on **Info** tab
2. Enable **Start on boot** and **Watchdog** so the service restarts automatically
3. Check the **Log** tab to confirm both connections succeeded:
   ```
   INFO - Connecting to MQTT Broker at core-mosquitto:1883
   INFO - Connected to MQTT Broker
   INFO - Initiating battery monitor
   ```

---

## Step 7 — Verify in Home Assistant

With MQTT auto-discovery enabled, Home Assistant will automatically create a **Red Reactor** device:

- Navigate to **Settings > Devices & Services > MQTT**
- A new device will appear with your configured name, containing entities for voltage, current, battery level, CPU temperature, external power state, and more
- **Restart** and **Shutdown** buttons are also available as entities on the device

---

## Troubleshooting

**No device appears in Home Assistant**
- Confirm the MQTT integration is configured and connected
- Check the add-on log for connection errors
- Verify the MQTT broker username and password are correct

**"Unable to connect to the Red Reactor" in logs**
- Ensure the Red Reactor board is firmly seated on the GPIO header
- Confirm I2C was enabled and both reboots were completed
- Check via **Settings > System > Hardware** that I2C is listed

**Service stops unexpectedly**
- Enable the **Watchdog** option on the add-on to restart it automatically on failure

If you have problems, create an [issue](https://github.com/mreditor97/redreactor/issues) on the GitHub repository.
