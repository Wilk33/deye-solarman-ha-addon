# Changelog

## 1.3.1

- Remove `US version grounding fault`, `Grid Standard`, `Configured Grid Phases` and `Allow Remote` from the control catalog. Previously published MQTT Discovery entries for these keys are removed during the next runtime start.
- Add `advanced.detailed_logs`, disabled by default. When disabled, per-message MQTT publication logs and debug rows are suppressed; an expected Solarman TCP close is a compact warning without a traceback. When enabled, the add-on logs debug details, every MQTT publication, register ranges and full tracebacks.

## 1.3.0

- Add a shared `/share/entity_owners.json` registry with an OS file lock and ownership by inverter serial, MQTT component and canonical key.
- Keep state, RAW, attribute and Discovery topics shared and retain existing unique IDs. Scope control commands, transport availability and MQTT client IDs by source; include Discovery origin.
- Serialize selection, reset and deletion with ownership. Return HTTP 409 and roll back configuration on conflicts; reconcile existing enabled definitions at startup without stealing foreign entries.
- Guard publication and delayed Discovery deletion under the registry lock until MQTT QoS 1 acknowledgement. Recheck control ownership immediately before writing registers.
- Show the owner and disable occupied MQTT choices in all three Ingress tabs; refresh ownership metadata every five seconds without replacing unsaved form fields.
- Add multiprocess, MQTT handoff and HTTP regression tests. The shared protocol prepares for the future RS485 adapter; existing external Sunsynk add-ons do not participate in this registry.

## 1.2.1

- Rename the Ingress tabs to `Sensory` and `Sterowanie`; remove per-control Test buttons.
- Correct R102 to Battery Capacity in Ah while retaining its MQTT key and custom names.
- Resolve R108/R109 limits from rated power: 120/150/190/210/240 A for 5/6/8/10/12 kW; reject writes when no verified limit is available.
- Shift the R336 Parallel Modbus SN field by 10 bits on read and write, preserving neighboring fields.
- Show R182/R184 as RAW/UNKNOWN and block writes pending firmware-specific mappings. Keep R139 readable without inventing an unverified maximum or permitting writes.
- Represent unknown enum fields, including zero in R178/R228, as UNKNOWN rather than invalid reads. Reject writes from unknown states and mark selected MQTT controls unavailable until recognized.
- Migrate saved catalog definitions and scan decoding while preserving user names and schedules. Remove previously published controls that are now read-only.
- Preserve these corrections in a source-controlled overlay applied by the Sunsynk importer.

## 1.2.0

- Extract the runtime into `packages/deye_inverter_core` and inject the Solarman adapter from `apps/deye-solarman/src` through shared read/write contracts.
- Split canonical model maps into telemetry, telemetry-plus and control with a checksummed catalog index. Generate the existing HAOS build context and legacy telemetry URL from canonical sources; verify generated files in CI.

- Add the Ingress `Encje sterowania` workspace with a separate scan, filters, MQTT selection, polling settings, reset, deletion, and per-entity read-only Test.
- Bundle 119 control definitions from the pinned Sunsynk three-phase LV profile, including numbers, switches, selects, program times and system time.
- Publish selected controls through MQTT Discovery and process commands through the shared Solarman lock, preserving register bitmasks and checking dynamic limits and read-back.
- Reject retained, stale, invalid and deselected commands. Do not retry uncertain writes; disable further writes until configuration is saved again or the add-on restarts.
- Correct the tab label to `Własne sensory`.

## 1.1.1

- Expand the SG04LP3 / SG05LP3 read-only map to 94 inverter definitions and 23 BMS definitions per pack, including separate BMS alarm and fault words, BMS temperatures and limits, phase measurements, generator measurements, and status flags.
- Add per-sensor ASCII `byte_order`; BMS serials use `low_high`, while the historical `high_low` decoder remains the default for all other ASCII data.
- Build the offline fallback from the same versioned catalog copied into the add-on image, and migrate legacy scanned BMS serial definitions to the corrected byte order without clearing MQTT selections.

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
