# Ubuntu / Standard Linux OS

This guide covers installing Red Reactor as a persistent background service on Ubuntu or any standard Debian-based Linux distribution running on a Raspberry Pi.

---

## Prerequisites

- A Raspberry Pi with a **Red Reactor** board attached
- Ubuntu 22.04+ (or equivalent Debian-based distro) — Python 3.10 or later required
- An accessible MQTT broker (e.g. Mosquitto running locally or on your Home Assistant instance)
- Root / `sudo` access

---

## Step 1 — Configure Boot Parameters

Two boot files need updating before the service will work correctly.

### cmdline.txt — enable TTY console

The service requires a TTY console to issue shutdown and restart commands. Verify that `console=tty1` is present in `/boot/firmware/cmdline.txt` (path may be `/boot/cmdline.txt` on older images):

```bash
cat /boot/firmware/cmdline.txt
```

If missing, add it — the file must remain a **single line**:

```bash
sudo nano /boot/firmware/cmdline.txt
# Add console=tty1 to the existing line, e.g.:
# console=serial0,115200 console=tty1 root=PARTUUID=... rootfstype=ext4 ...
```

### config.txt — enable I2C and GPIO power-off

Add the following to `/boot/firmware/config.txt` (path may be `/boot/config.txt` on older images):

```bash
sudo nano /boot/firmware/config.txt
```

```
enable_uart=1
dtparam=i2c_vc=on
dtparam=i2c_arm=on
dtoverlay=gpio-poweroff,gpiopin=14,active_low=1,timeout_ms=8000
```

`enable_uart=1` activates the hardware UART (required for the serial console). `dtparam=i2c_arm=on` enables the I2C bus. `dtoverlay=gpio-poweroff` ensures the Pi drives GPIO 14 low after shutdown, allowing the Red Reactor to cut power cleanly.

Reboot after saving both files.

---

## Step 2 — Enable I2C

Follow the [Enabling I2C](Enabling-I2C) guide (Standard Linux section), then return here.

---

## Step 3 — Install Python 3.10+

```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv
python3 --version   # must be 3.10 or later
```

---

## Step 4 — Create a Dedicated User and Directories

Running as a dedicated user limits the service's permissions:

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin redreactor
sudo mkdir -p /var/lib/redreactor /etc/redreactor
sudo chown redreactor:redreactor /var/lib/redreactor /etc/redreactor
```

---

## Step 5 — Install Red Reactor into a Virtualenv

```bash
sudo -u redreactor python3 -m venv /var/lib/redreactor/.venv
sudo -u redreactor /var/lib/redreactor/.venv/bin/pip install redreactor
```

---

## Step 6 — Configure Red Reactor

```bash
sudo curl -fsSL https://raw.githubusercontent.com/mreditor97/redreactor/master/extras/config.yaml \
  -o /etc/redreactor/config.yaml
sudo chown redreactor:redreactor /etc/redreactor/config.yaml
sudo nano /etc/redreactor/config.yaml
```

See the [Configuration](Configuration) guide for a full reference of every option. At minimum, set your MQTT broker details and hostname:

```yaml
mqtt:
  broker: 192.168.1.100
  port: 1883
  user: your_mqtt_username
  password: your_mqtt_password

hostname:
  name: redreactor-pi     # Used in MQTT topics — must be unique per device
  pretty: Red Reactor Pi
```

---

## Step 7 — Allow Shutdown and Restart Commands

The service needs permission to call `sudo shutdown` when instructed via MQTT:

```bash
sudo visudo -f /etc/sudoers.d/redreactor
```

Add:

```
redreactor ALL=(ALL) NOPASSWD: /sbin/shutdown
```

---

## Step 8 — Install the systemd Service

```bash
sudo curl -fsSL https://raw.githubusercontent.com/mreditor97/redreactor/master/extras/redreactor.service \
  -o /etc/systemd/system/redreactor.service

sudo systemctl daemon-reload
sudo systemctl enable redreactor
sudo systemctl start redreactor
```

---

## Step 9 — Verify the Service

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
# or
tail -f /etc/redreactor/redreactor.log
```

---

## Updating

```bash
sudo -u redreactor /var/lib/redreactor/.venv/bin/pip install --upgrade redreactor
sudo systemctl restart redreactor
```

---

## Troubleshooting

**"Unable to connect to the Red Reactor" on startup**
- Run `i2cdetect -y 1` and confirm address `0x40` is listed
- Ensure the Red Reactor board is firmly seated on the GPIO header
- Verify I2C is enabled — see [Enabling I2C](Enabling-I2C)

**Service fails to connect to MQTT**
- Test the broker: `mosquitto_sub -h <broker_ip> -u <user> -P <pass> -t "#" -v`
- Check credentials in `/etc/redreactor/config.yaml`
- If `exit_on_fail: true`, the service exits on failure — check `journalctl -u redreactor`

**Permission denied on shutdown**
- Verify: `sudo -u redreactor sudo shutdown --help` should not prompt for a password

If you have problems, create an [issue](https://github.com/mreditor97/redreactor/issues) on the GitHub repository.
