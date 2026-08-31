# Changelog

## 0.3.0

- Add a Home Assistant Ingress configuration panel for scanning, selecting MQTT entities, and editing decoding and polling values without using the terminal or editing YAML.
- Keep `scan_only` running with MQTT disabled so the Ingress panel remains available after the automatic scan.
- Serialize panel scans and MQTT polling reads to avoid concurrent Solarman Modbus requests.

## 0.2.1

- Disable all default MQTT entities so normal monitoring publishes only sensors explicitly selected in `detected_sensors.yaml` or enabled in `user_sensors.yaml`.

## 0.2.0

- Add manual, read-only candidate scanning for 68 documented SG04LP3 / SG05LP3 telemetry values and 14 diagnostic values per BMS pack.
- Store scan evidence and persistent user selection in `/share/deye_solarman_candidate_scan.json` and `/config/detected_sensors.yaml`.
- Publish only entries selected with `monitor: true`; `scan_only` does not connect to MQTT or create discovery entities.
- Correct per-pack BMS register offsets and temperature and SOC scaling in the default profile.

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
