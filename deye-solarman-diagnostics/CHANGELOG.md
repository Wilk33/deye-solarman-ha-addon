# Changelog

## 1.1.0

- Move the complete remote register map into `deye_sg04_sg05_3ph_lv_catalog.yaml` version 2: 68 live inverter definitions and a validated BMS-pack template for one to ten packs are now editable on GitHub without a new add-on image.
- Keep `catalog.py` as an offline emergency fallback and add a regression test that proves the remote map matches the built-in map for four packs and expands correctly to ten packs.

## 1.0.0

- Promote Deye Solarman Diagnostics from beta to the first stable release after transport, scanning, MQTT Discovery, runtime reload, remote catalog, diagnostics, and custom-sensor workflows were validated together.
- Document the complete operating model, installation, configuration, MQTT topics, scan lifecycle, custom sensors, formula sandbox, diagnostics, and operational limits in the repository README.

## 0.8.1

- Treat an empty `/config/custom_sensors.yaml` list as a valid initial state, so the add-on starts before the first custom sensor is created.

## 0.8.0

- Add the `Wlasne sensory` Ingress workspace with standard manual Modbus sensors, MQTT selection, individual deletion, formula testing, a scrollable editor, and a centered expanded editor.
- Add persistent `/config/custom_sensors.yaml` definitions and automatic MQTT Discovery removal for deleted or deselected custom sensors.
- Add a restricted local formula interpreter with direct-register `sensor(...)` and `RAW(...)`, local variables and functions, `if`, `match/case`, and bounded `for ... in range(...)`.
- Add internal formula type `auto`, presented as `-` in the panel, so `return` values are published without a second register decoder.

## 0.7.0

- Apply saved MQTT selections, sensor reset, list deletion, and completed scans by reloading only the add-on polling and MQTT runtime, without restarting the add-on container.
- Queue MQTT Discovery removal when an individual panel sensor is deselected, so stale Home Assistant entities are removed during the automatic runtime reload.
- Audit all 68 built-in SG04LP3/SG05LP3 live register definitions against the public three-phase map and document the type, signedness, word-order, and temperature conversion result.

## 0.6.0

- Replace native Ingress select popups with theme-aware custom controls for filters and sensor decoding settings.
- Add `ascii` as a sensor type, use it for BMS serial candidates, and show printable ASCII beside every raw hexadecimal register sequence.
- Use compact terminal log rows with visible OK, warning, and error markers. Success is green, warning is dark yellow, errors are red, and informational rows keep the terminal theme color.

## 0.5.0

- Synchronize the Ingress document with Home Assistant theme variables at runtime, including theme changes after the panel is open.
- Add panel actions to reset found sensors to catalog defaults and clear the local found-sensor list while refreshing the cached GitHub catalog.
- Remove retained MQTT Discovery configurations for deselected or deleted panel sensors on the following add-on restart.
- Keep scan, reset, delete, and MQTT-selection save as separate operations with explicit confirmation for destructive local actions.

## 0.4.0

- Reconnect the Solarman TCP client immediately after the logger closes the connection, instead of continuing to poll a dead session.
- Use the Home Assistant temperature unit `°C` in MQTT Discovery so BMS and inverter temperature entities are accepted as temperature sensors.
- Replace fixed Ingress colors with Home Assistant theme CSS variables for light and dark themes.
- Refresh a validated register-catalog overlay from GitHub on startup, cache its last valid copy in `/config`, and fall back to built-in definitions when it is unavailable.

## 0.3.6

- Parse the MQTT service payload returned by the Home Assistant Supervisor API when it is wrapped in a `data` object.

## 0.3.5

- Use the Home Assistant Supervisor MQTT service credentials by default, matching the reference Sunsynk/Deye multi add-on behaviour on HAOS.
- Keep an explicit manual MQTT fallback for external brokers and log the selected connection source without exposing secrets.

## 0.3.4

- Log the number of enabled sensors, MQTT connection confirmation, every Discovery publish topic, and delivery failures to diagnose missing Home Assistant entities.
- Wait for MQTT broker connection and Discovery publication instead of continuing after an unconfirmed client call.

## 0.3.3

- Fix a browser JavaScript syntax error that prevented the Ingress panel from loading scan data or responding to button clicks.

## 0.3.2

- Add browser console diagnostics and INFO-level Ingress request logging for the panel, API calls, and scan action.

## 0.3.1

- Fix panel API paths under Home Assistant Ingress by generating the browser base URL from the Supervisor `X-Ingress-Path` header.

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
