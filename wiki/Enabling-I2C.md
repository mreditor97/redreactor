# Enabling I2C

The Red Reactor uses I2C to communicate with the INA219 power monitor chip. I2C must be enabled on your Raspberry Pi before the service will start.

---

## Standard Linux (raspi-config)

For Raspberry Pi OS, Ubuntu, or any distro that includes `raspi-config`:

```bash
sudo raspi-config
```

Navigate to **Interface Options > I2C > Enable**, then reboot.

Verify the INA219 is detected at address `0x40`:

```bash
sudo apt install -y i2c-tools
i2cdetect -y 1
```

You should see `40` in the output grid. If it does not appear, check that the Red Reactor board is firmly seated on the GPIO header.

---

## Home Assistant OS

HAOS does not include `raspi-config`. Two methods are available:

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

A full walkthrough is also available on the [Home Assistant website](https://www.home-assistant.io/common-tasks/os/#enable-i2c).

---

## Docker

I2C must be enabled on the **host OS** before starting the container. Follow the Standard Linux steps above, then confirm the device node exists:

```bash
ls /dev/i2c-*
```

The `docker-compose.yaml` must map the device into the container:

```yaml
devices:
  - /dev/i2c-1:/dev/i2c-1
```
