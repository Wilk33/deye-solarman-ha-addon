# Deye Solarman Diagnostics

## Overview

This add-on is a dedicated diagnostic path for Deye battery pack data through a local Solarman logger.

It is designed to complement an existing fast RS485 channel such as `Sunsynk or Deye Inverter add-on (multi)`, not replace it.

## Features

- startup connectivity probe against a chosen holding register
- conservative single-client polling over Solarman TCP
- configurable sensor definitions based on one or more registers
- MQTT Discovery publishing for Home Assistant
- raw register and decoded value publishing
- default definitions separated from user overrides
- JSON scan report exported to `/share`

## Configuration

Example:

```yaml
logger:
	host: 192.168.1.100
	port: 8899
	serial_number: 1234567890
	modbus_id: 1
	timeout: 3
	reconnect_delay: 10

mqtt:
	host: core-mosquitto
	port: 1883
	username: mqtt-user
	password: mqtt-password
	client_id: deye-solarman-diagnostics
	base_topic: deye_solarman
	discovery_prefix: homeassistant
	retain: true

inverter:
	serial_number: "2507092018"
	name: Deye Solarman Diagnostics
	manufacturer: Deye
	model: SG05LP3

profiles:
	default_profile:
		- deye_battery_packs
	overrides_file: /config/user_sensors.yaml
	state_file: /config/runtime_state.json
	scan_report_file: /share/deye_solarman_scan_report.json

polling:
	default_interval: 60
	slow_interval: 600
	read_message_spacing: 0.05
	batch_gap: 1
	max_registers_per_request: 20
	publish_unchanged_every: 900
	startup_probe_register: 10040
	startup_probe_count: 1
	allow_reconnect: true

advanced:
	emit_raw_topics: true
	emit_scan_report: true
```

## User overrides

Create `/addon_configs/<slug>/user_sensors.yaml` and redefine only the fields you need to change.

Example:

```yaml
sensors:
	- key: battery_1_current
		type: int16
		multiplier: 0.1
		read_every: 30
		report_every: 120
```

## Output

- MQTT Discovery topics under `homeassistant`
- state topics under `deye_solarman/<inverter_serial>/...`
- optional scan report in `/share/deye_solarman_scan_report.json`
