# Red Reactor MQTT Client for Home Automation

This is a Red Reactor MQTT Client service that is designed to run as a background application to monitor battery status, and to publish that data to a MQTT broker.

**Installation instructions can be found [here](https://github.com/mreditor97/redreactor/wiki).**

Functionality includes:

- Background application that continuously monitors the battery status, and will safely shutdown if required
- Configurable battery shutdown level
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
  - Under-voltage and Throttled problem states
  - Battery Warning Threshold
  - Battery Voltage Minimum and Maximum
  - Report Interval
- Commands:
  - Immediate Shutdown
  - Immediate Restart
  - Change the Battery Warning Threshold
  - Change the Battery Voltage Minimum and Maximum
  - Change the Report Interval
- Power events (power lost, power restored, low battery, shutdown started) for automations
- Optional TLS for the MQTT connection
- A `--check` option that reads the Red Reactor once and exits, to test the I2C setup
- Provides `systemd` service example, so it can be started as a service on system boot

If you haven't already got yourself a Red Reactor (An uninterruptible battery powered backup for your Raspberry Pi), one can be purchased from there [website](https://theredreactor.com).

## Home Assistant

Connecting your Home Assistant instance to the same MQTT Broker as your Red Reactor will allow your Red Reactor to be auto discovered by your Home Assistant instance. It will give you access to all the readings available from the Red Reactor sensors, and allows full configuration of the Red Reactor on the fly - it even adds the ability to reboot and shutdown your device at the push of a button.

The Red Reactor uses Home Assistant's device discovery, one message on `homeassistant/device/redreactor_<hostname>/config` that holds every entity. Versions before this published one message per entity. On start it moves Home Assistant over using its migration steps, so existing entities keep their entity IDs, names and history. The old raw CPU stat sensor is removed, replaced by the Under-voltage and Throttled binary sensors. New entities get entity IDs from the device and field name, such as `sensor.red_reactor_pi_voltage`.

The Power event entity fires `power_lost`, `power_restored`, `low_battery` (the first reading at the battery shutdown level, on battery) and `shutdown_started` (a low battery or Shutdown button shutdown), so an automation can notify you without watching other entities.

When Home Assistant restarts it publishes `online` to `homeassistant/status`. The Red Reactor listens for this and sends its discovery configuration and latest readings straight away, rather than leaving the entities unknown until the next report. If your Home Assistant MQTT integration uses a different birth message, set `homeassistant.status_topic` and `homeassistant.status_online` in the configuration file to match.

There is also a [Home Assistant Add-on](https://github.com/mreditor97/homeassistant-addons) available for Supervisor users. Installation instructions can be found in the [wiki](https://github.com/mreditor97/redreactor/wiki).

## MQTT

### State

Topic `redreactor/your-configured-hostname/state`

```json
{
  "voltage": 4.164,
  "current": -2.1799,
  "power": 0.009,
  "battery_level": 100,
  "external_power": "ON",
  "charging": "OFF",
  "cpu_temperature": 49.1,
  "cpu_stat": "OK",
  "under_voltage": "OFF",
  "throttled": "OFF",
  "battery_warning_threshold": 10,
  "battery_voltage_minimum": 2.6,
  "battery_voltage_maximum": 4.2,
  "report_interval": 30,
  "battery_capacity": 3000,
  "battery_time_remaining": null
}
```

#### State Description

- `voltage` is the Voltage of the connected batteries
- `current` is the current through the batteries in mA, negative while they are discharging and positive while they are charging
- `power` is the power drawn from the batteries in W
- `battery_level` is the percentage value of charge left in the batteries
- `external_power` is whether the batteries are connected to an external power source or not
- `charging` is whether the batteries are currently being charged
- `cpu_temperature` read via `cat /sys/class/thermal/thermal_zone0/temp` gets the CPU Temperature
- `cpu_stat` read via `cat /sys/devices/platform/soc/soc:firmware/get_throttled` gets the CPU Stat in a human readable format
- `under_voltage` is `ON` while the Raspberry Pi reports under-voltage now, from the same throttling state as `cpu_stat`. `null` when it can't be read
- `throttled` is `ON` while the CPU is slowed down now: frequency capped, throttled, or at the soft temperature limit. `null` when it can't be read
- `battery_warning_threshold` is the battery percentage at or below which, while running on battery, a safe shutdown of the device is started (after 3 consecutive readings, so a brief voltage dip doesn't trigger it). If the device starts up below this level while charging it stays on; without external power it shuts down again
- `battery_voltage_minimum` is the voltage at which is to be considered the lowest allowable before initiating a safe shutdown
- `battery_voltage_maximum` is the voltage at which is to be considered the maximum at which the battery can be (this is used in the calculation of the `battery_level`)
- `report_interval` is the reporting interval at which the data will be published onto the **state** topic
- `battery_capacity` is the total capacity of the batteries in mAh (with two cells in parallel, the sum of both), set it from Home Assistant or the command topic. `0` means not set
- `battery_time_remaining` is a rough estimate of the days left on battery before the low battery shutdown, from `battery_capacity`, `battery_level` above `battery_warning_threshold` and `current`. It is `null` (unknown in Home Assistant) while there is external power or `battery_capacity` is `0`. The battery level is worked out from the voltage, which isn't linear with the charge left, so treat it as a guide

### Status

Topic `redreactor/hostname/status`

Data `online` or `offline`

### Event

Topic `redreactor/your-configured-hostname/event`

Data `{"event_type": "power_lost"}`, with `power_lost`, `power_restored`, `low_battery` or `shutdown_started`. Not retained, so an old event isn't replayed when Home Assistant reconnects.

### Command

Topic `redreactor/your-configured-hostname/set/chosen-command`

Command topic | value:

- `battery_warning_threshold` | value (int)
- `battery_voltage_minimum` | value (float)
- `battery_voltage_maximum` | value (float)
- `report_interval` | value (int)
- `battery_capacity` | value (int, mAh, `0` to `20000`, `0` for not set)
- `restart` | no value required
- `shutdown` | no value required

## Configuration

`extras/config.yaml` is an example configuration file. Some options that are not in it:

- `mqtt.user` and `mqtt.password` default to empty, which connects anonymously. Set both for a broker that needs a login
- `ina.bus` is the I2C bus the Red Reactor is on (default `1`)
- `ina.adc_samples` is how many samples the INA219 averages for each reading: `1` (default, a single 12-bit sample), `2`, `4`, `8`, `16`, `32`, `64` or `128`. More samples give steadier readings at no CPU cost, 128 takes about 68 ms per reading
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

- `battery.internal_resistance` is the battery's internal resistance in mΩ (default `35`, `0` turns it off), see [Battery level](#battery-level)
- `battery.average_readings` is how many monitor readings are averaged for `battery_level` (default `6`, 30 seconds at the default `ina.monitor_interval`, `1` turns it off), see [Battery level](#battery-level)
- `battery.curve` maps the battery's resting voltage to its level, see [Battery level](#battery-level)
- `fields.<field>.name` is used in the MQTT topics and the state JSON, so it must be letters, digits and `_`, not starting with a digit
- `fields.<field>.default_entity_id` sets the entity ID Home Assistant creates the entity with, for example `sensor.ups_voltage`. The older `object_id` option still works but is deprecated by Home Assistant

The configuration is checked at start-up. Any invalid value stops the service with one line naming each problem, for example `` `ina.monitor_interval` must be a number of seconds from 0.1 to 86400 ``. The limits checked include:

- `ina.monitor_interval` from 0.1 to 86400 seconds, and `homeassistant.discovery_interval` from 1 to 86400 seconds, or `0` to only send discovery on connect and when Home Assistant comes online
- `mqtt.timeout` (the keepalive) from 0 to 65535 seconds, and `mqtt.transport` one of `tcp`, `websockets` or `unix`
- `system.shutdown` and `system.restart` must be commands that can be split into arguments, so an unclosed quote is found at start-up rather than when the battery is low
- `status.online` and `status.offline` must be different, non-empty text

A shutdown or restart command that hasn't finished after 60 seconds is given up on, and the service exits. Settings stored in the database file are held to the same `min` and `max` as values sent over MQTT. If the database or log file can't be written, the service keeps running with a warning, as the battery monitoring matters more.

### Battery level

By default `battery_level` is a straight line from `battery_voltage_minimum` (0%) to `battery_voltage_maximum` (100%). A Li-ion battery's voltage doesn't fall evenly as it discharges, and it sags further the more current is drawn, so the level can jump around under load. The level is worked out from the average of the last `battery.average_readings` readings (6 by default), which smooths out brief current spikes, as the Red Reactor manual recommends. Two more settings improve it:

1. **Internal resistance** (`battery.internal_resistance` in the configuration file). The voltage sags under load by about current × resistance, so that is added back before working out the level (and taken off while charging). With the Pi idle, note the voltage and current, then put it under load (for example `stress -c 4`) and note them again. The resistance in mΩ is the voltage drop in mV divided by the current rise in A. This includes the holder, wiring and board as well as the cell, so it is usually higher than the datasheet figure. The default of 35 mΩ is the maximum initial AC impedance in the Samsung INR18650-35E datasheet; as the real value is usually higher, the default under-corrects, which errs towards shutting down early rather than late. With two cells in parallel, measure them together; the result is the combined resistance.
2. **Voltage curve** (`battery.curve` in the configuration file). Pairs of `[resting voltage, level %]`, with rising voltages. The level is interpolated between them, and the ends are clamped. When a curve is set, `battery_voltage_minimum` and `battery_voltage_maximum` no longer affect the level.

   For example, for a Samsung INR18650-35E:

   ```yaml
   battery:
     internal_resistance: 35 # mΩ, your measured value
     average_readings: 6
     curve:
       - [2.80, 0]
       - [3.08, 5]
       - [3.25, 10]
       - [3.39, 15]
       - [3.44, 20]
       - [3.55, 30]
       - [3.63, 40]
       - [3.71, 50]
       - [3.80, 60]
       - [3.89, 70]
       - [3.99, 80]
       - [4.06, 90]
       - [4.08, 95]
       - [4.16, 100]
   ```

   This curve was read off the 0.2 A discharge trace in the [lygte-info.dk review of the Samsung INR18650-35E](https://lygte-info.dk/review/batteries2012/Samsung%20INR18650-35E%203500mAh%20%28Pink%29%20UK.html), with the level as the share of the 3.40 Ah the cell gave down to 2.8 V. It was read off a chart, so the voltages are approximate (about ±0.01 V), and your own cells will differ a little with age and temperature. No curve is used unless you set one. One way to measure your own is to charge fully, set `battery.internal_resistance`, then run on battery at a steady load until shutdown, and use the voltage history from Home Assistant: with a steady current the charge used is proportional to the time, so the voltage at 10% of the run time is the 90% point, and so on.

The log file is rotated at 1 MB, keeping 3 old files.

To check the Red Reactor can be read, without connecting to MQTT:

```shell
python -m redreactor --config /etc/redreactor/config.yaml --check
```

If there are more features that you would like to see supported, let me know!
