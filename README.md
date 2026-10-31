# Red Reactor MQTT Client for Home Automation

This is a Red Reactor MQTT Client service that is designed to run as a background application to monitor battery status, and to publish that data to a MQTT broker.

**Installation instructions can be found [here](https://github.com/mreditor97/redreactor/wiki).**

Functionality includes:

- Background application that continuously monitors the battery status, and will safely shutdown if required
- Configurable shutdown level, and an optional limit on how long to run on battery
- The configuration file can be used to override specific topics and entities
- Connects to a MQTT broker, and publishes the service status, data and enables command topics
- Published data includes:
  - Voltage
  - Current
  - Power
  - Battery Level
  - External Power Status
  - Charging Status
  - CPU Temperature
  - CPU Status
  - CPU Status Raw
  - Battery Warning Threshold
  - Battery Voltage Minimum and Maximum
  - Report Interval
  - Battery Runtime Limit
- Commands:
  - Immediate Shutdown
  - Immediate Restart
  - Change the Battery Warning Threshold
  - Change the Battery Voltage Minimum and Maximum
  - Change the Report Interval
  - Change the Battery Runtime Limit
- Optional TLS for the MQTT connection
- A `--check` option that reads the Red Reactor once and exits, to test the I2C setup
- Provides `systemd` service example, so it can be started as a service on system boot

If you haven't already got yourself a Red Reactor (An uninterruptible battery powered backup for your Raspberry Pi), one can be purchased from there [website](https://theredreactor.com).

## Home Assistant

Connecting your Home Assistant instance to the same MQTT Broker as your Red Reactor will allow your Red Reactor to be auto discovered by your Home Assistant instance. It will give you access to all the readings available from the Red Reactor sensors, and allows full configuration of the Red Reactor on the fly - it even adds the ability to reboot and shutdown your device at the push of a button.

There is also a [Home Assistant Add-on](https://github.com/mreditor97/homeassistant-addons) available for Supervisor users. Installation instructions can be found in the [wiki](https://github.com/mreditor97/redreactor/wiki).

## MQTT

### State

Topic `redreactor/your-configured-hostname/state`

```json
{
  "voltage": 4.164,
  "current": 2.1799,
  "power": 0.009,
  "battery_level": 100,
  "external_power": "ON",
  "charging": "OFF",
  "cpu_temperature": 49.1,
  "cpu_stat": "OK",
  "cpu_stat_raw": 0,
  "battery_warning_threshold": 10,
  "battery_voltage_minimum": 2.6,
  "battery_voltage_maximum": 4.2,
  "report_interval": 30,
  "battery_runtime_limit": 0,
  "battery_capacity": 3000,
  "battery_time_remaining": null
}
```

#### State Description

- `voltage` is the Voltage of the connected batteries
- `current` is the Current draw from the batteries in mA (negative while charging)
- `power` is the power drawn from the batteries in W
- `battery_level` is the percentage value of charge left in the batteries
- `external_power` is whether the batteries are connected to an external power source or not
- `charging` is whether the batteries are currently being charged
- `cpu_temperature` read via `cat /sys/class/thermal/thermal_zone0/temp` gets the CPU Temperature
- `cpu_stat` read via `cat /sys/devices/platform/soc/soc:firmware/get_throttled` gets the CPU Stat in a human readable format
- `cpu_stat_raw` read via `cat /sys/devices/platform/soc/soc:firmware/get_throttled` gets the CPU Stat
- `battery_warning_threshold` is the battery percentage at or below which, while running on battery, a safe shutdown of the device is started (after 3 consecutive readings, so a brief voltage dip doesn't trigger it). If the device starts up below this level while charging it stays on; without external power it shuts down again
- `battery_voltage_minimum` is the voltage at which is to be considered the lowest allowable before initiating a safe shutdown
- `battery_voltage_maximum` is the voltage at which is to be considered the maximum at which the battery can be (this is used in the calculation of the `battery_level`)
- `report_interval` is the reporting interval at which the data will be published onto the **state** topic
- `battery_runtime_limit` is the number of minutes to run on battery before a safe shutdown, whatever the charge. `0` turns it off
- `battery_capacity` is the capacity of the batteries in mAh, set it from Home Assistant or the command topic. `0` means not set
- `battery_time_remaining` is a rough estimate of the minutes left on battery before the low battery shutdown, from `battery_capacity`, `battery_level` above `battery_warning_threshold` and `current`. It is `null` (unknown in Home Assistant) while there is external power or `battery_capacity` is `0`. The battery level is worked out from the voltage, which isn't linear with the charge left, so treat it as a guide

### Status

Topic `redreactor/hostname/status`

Data `online` or `offline`

### Command

Topic `redreactor/your-configured-hostname/set/chosen-command`

Command topic | value:

- `battery_warning_threshold` | value (int)
- `battery_voltage_minimum` | value (float)
- `battery_voltage_maximum` | value (float)
- `report_interval` | value (int)
- `battery_runtime_limit` | value (int, minutes, `0` to turn off)
- `battery_capacity` | value (int, mAh, `0` to `20000`, `0` for not set)
- `restart` | no value required
- `shutdown` | no value required

## Configuration

`extras/config.yaml` is an example configuration file. Some options that are not in it:

- `ina.bus` is the I2C bus the Red Reactor is on (default `1`)
- `mqtt.tls` turns on TLS for the MQTT connection:

  ```yaml
  mqtt:
    port: 8883
    tls:
      enabled: true
      ca_certs: /etc/redreactor/ca.crt # Leave out to use the system certificates
      certfile: /etc/redreactor/client.crt # Only for client certificate login
      keyfile: /etc/redreactor/client.key # Only for client certificate login
      insecure: false # true skips the hostname check, for testing only
  ```

- `fields.<field>.default_entity_id` sets the entity ID Home Assistant creates the entity with, for example `sensor.ups_voltage`. The older `object_id` option still works but is deprecated by Home Assistant

The log file is rotated at 1 MB, keeping 3 old files.

To check the Red Reactor can be read, without connecting to MQTT:

```shell
python -m redreactor --config /etc/redreactor/config.yaml --check
```

If there are more features that you would like to see supported, let me know!
