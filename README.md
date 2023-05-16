# Red Reactor MQTT Client for Home Automation

This is a Red Reactor MQTT Client service that is designed to run as a background application to monitor battery status, and to publish that data to a MQTT broker.

Functionality includes:

- Background application that continuously monitors the battery status, and will safely shutdown if required
- The configuration file can be used to override specific topics and entities
- Connects to a MQTT broker, and publishes the service status, data and enables command topics
- Published data includes:
  - Voltage
  - Current
  - Battery Level
  - External Power Status
  - CPU Temperature
  - CPU Status
  - Battery Warning Threshold
  - Battery Voltage Minimum and Maximum
  - Report Interval
- Commands:
  - Immediate Shutdown
  - Immediate Restart
  - Change the Battery Warning Threshold
  - Change the Battery Voltage Minimum and Maximum
  - Change the Report Interval
- Provides `systemd` service example, so it can be started as a service on system boot

## Home Assistant

Connecting your Home Assistant instance to the same MQTT Broker as your Red Reactor will allow your Red Reactor to be auto discovered by your Home Assistant instance. It will give you access to all the readings available from the Red Reactor sensors, and allows full configuration of the Red Reactor on the fly - it even adds the ability to reboot and shutdown your device at the push of a button.

There is also a [Home Assistant Add-on](https://github.com/mreditor97/homeassistant-addons) available for Supervisor users.

## MQTT

### State

Topic `redreactor/your-configured-hostname/state`

```json
{
  "voltage": 4.164,
  "current": 2.1799,
  "battery_level": 100,
  "external_power": "ON",
  "cpu_temperature": 49.1,
  "cpu_stat": 0,
  "battery_warning_threshold": 10,
  "battery_voltage_minimum": 2.6,
  "battery_voltage_maximum": 4.2,
  "report_interval": 30
}
```

#### State Description

- `voltage` is the Voltage of the connected batteries
- `current` is the Current draw from the batteries
- `battery_level` is the percentage value of charge left in the batteries
- `external_power` is whether the batteries are connected to an external power source or not
- `cpu_temperature` read via `cat /sys/class/thermal/thermal_zone0/temp` gets the CPU Temperature
- `cpu_stat` read via `cat /sys/devices/platform/soc/soc:firmware/get_throttled` gets the CPU Stat
- `battery_warning_threshold` is a percentage value below 100% that once crossed will initiate a safe shutdown of the device
- `battery_voltage_minimum` is the voltage at which is to be considered the lowest allowable before initiating a safe shutdown
- `battery_voltage_maximum` is the voltage at which is to be considered the maximum at which the battery can be (this is used in the calculation of the `battery_level`)
- `report_interval` is the reporting interval at which the data will be published onto the **state** topic

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
- `restart` | no value required
- `shutdown` | no value required

If there are more features that you would like to see supported, let me know!
