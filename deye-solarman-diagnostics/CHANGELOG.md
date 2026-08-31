# Changelog

## 0.1.4

- Validate Solarman logger and user sensor configuration before polling.
- Correctly decode non-contiguous sensor register lists and respect MQTT retain and polling options.
- Recover safely after startup connection failures and protect runtime state files from partial writes.

## 0.1.3

- Fix the default profile option format required by the Home Assistant configuration editor.

## 0.1.2

- Pin pysolarmanv5 and PyYAML to published releases compatible with Alpine Linux.

## 0.1.1

- Install Python dependencies in an isolated virtual environment compatible with Alpine Linux PEP 668 protections.

## 0.1.0

- Initial HAOS add-on scaffold
- Python runtime for Solarman TCP polling and MQTT discovery
- Default sensor profile for four Deye battery packs
- User override support and scan report export
