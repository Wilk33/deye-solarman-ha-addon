# Multi-Add-on Architecture and Register Catalog Proposal

## Status and scope

This is a design decision for the next development stage. It creates no second Home Assistant application, changes no current add-on configuration, and enables no register writes.

The repository will ultimately provide two Home Assistant add-ons:

- `Deye Solarman Local` - local access through a Solarman TCP logger while the logger may remain connected to the Deye/Solarman cloud.
- `Deye RS485 Local` - direct local Modbus RTU access through a USB-RS485 adapter.

They share one Python core and one catalog format. They differ only in the transport adapter, transport-specific configuration, permissions, and supported map selection. The current `deye-solarman-diagnostics/` add-on remains the released compatibility path until a migration release is prepared.

## Target repository structure

```text
repository.yaml
apps/
  deye-solarman/                 # Future installable add-on, unique slug
  deye-rs485/                    # Future installable add-on, unique slug
packages/
  deye_inverter_core/             # One transport-independent Python source package
catalogs/
  schemas/                        # Schema definitions and validation fixtures
  models/
    deye_sg04_sg05_3ph_lv/
      catalog-index.yaml
      telemetry.yaml
      telemetry-plus.yaml
      control.yaml
docs/
  architecture/
tests/
  core/
  transports/
  catalogs/
```

Only completed application directories receive a `config.yaml`. This prevents Home Assistant Supervisor from exposing unfinished work in the add-on store.

## Shared core and transport boundary

The common core owns catalog loading, map selection, decoding, scan orchestration, scheduling, MQTT Discovery, persistent selections, custom formulas, ingress UI, audit reports, and logging. It must not import a Solarman TCP or Modbus RTU client directly.

The core receives a read-only transport with this contract:

```python
class RegisterTransport(Protocol):
    def connect(self) -> None: ...
    def close(self) -> None: ...
    def read_holding_registers(self,start: int,count: int) -> list[int]: ...
    def reconnect(self) -> None: ...
    @property
    def transport_id(self) -> str: ...
```

`SolarmanTcpTransport` wraps `pysolarmanv5`. `ModbusRtuTransport` wraps the selected RTU library. Neither adapter decides how a register is decoded or how MQTT is published.

Write support is deliberately separate:

```python
class WritableRegisterTransport(RegisterTransport,Protocol):
    def write_holding_registers(self,start: int,values: list[int]) -> None: ...
```

Selecting a control map does not make the transport writable. The add-on must explicitly arm control and the selected command must list the active transport as supported.

## Build and packaging rule

Docker cannot copy files outside its build context. An add-on Dockerfile therefore must not rely on `COPY ../packages/deye_inverter_core` when Supervisor builds only one add-on directory.

The preferred release design is GitHub Actions building two self-contained multi-architecture images from repository root and publishing them to GHCR. Each completed add-on references its own image, while both images receive the core from `packages/deye_inverter_core`.

Before GHCR publishing exists, a release tool may copy the core into each add-on build context. The source of truth remains `packages/deye_inverter_core`; CI must fail if either packaged copy differs from it. Manual edits to copied release artifacts are forbidden.

## Catalog bundle model

Each inverter family owns one `catalog-index.yaml`. The index lists maps, transport compatibility, immutable revision, and checksums. It does not contain register definitions.

```yaml
format: 1
catalog_set: deye_sg04_sg05_3ph_lv
display_name: Deye SG04LP3 and SG05LP3 three-phase LV
revision: 2026.09.0
maps:
  telemetry:
    file: telemetry.yaml
    sha256: <release-specific SHA-256>
    purpose: telemetry
    transports: [solarman_tcp, modbus_rtu]
    writable: false
  telemetry_plus:
    file: telemetry-plus.yaml
    sha256: <release-specific SHA-256>
    purpose: telemetry_plus
    transports: [solarman_tcp]
    writable: false
  control:
    file: control.yaml
    sha256: <release-specific SHA-256>
    purpose: control
    transports: [solarman_tcp, modbus_rtu]
    writable: true
```

Every map is downloaded into a temporary file, checked against its declared checksum and schema, then atomically moved to cache. A failed refresh never replaces a valid cache. The index and every selected map must come from the same immutable Git commit, release tag, or release asset. The runtime must not mix an index from one mutable `main` revision with maps from another revision.

## Required map selection

The configuration requires at least one map ID. No map is forced as a hidden primary map.

```yaml
catalog:
  catalog_set: deye_sg04_sg05_3ph_lv
  source:
    kind: github_release
    url: https://github.com/Wilk33/deye-solarman-ha-addon/releases/download/catalog-2026.09.0/catalog-index.yaml
  selected_maps:
    - telemetry
  cache_directory: /config/deye_catalogs
  refresh_on_start: true
  timeout: 5
```

All of the following are valid minimum selections:

```yaml
selected_maps: [telemetry]
selected_maps: [telemetry_plus]
selected_maps: [control]
```

The loader enforces these rules:

- `selected_maps` is non-empty, has unique IDs, and every ID exists in the selected index.
- Every selected map supports the active transport.
- `telemetry_plus` is rejected for `modbus_rtu` before a connection or scan begins.
- Selecting `control` alone is valid, but does not permit a write.
- Duplicate sensor keys across selected read-only maps are a validation error.
- Register overlap is allowed only with an explicit `overlap_reason` and a distinct sensor key.
- An invalid, incompatible, or checksum-failed selected map fails the full bundle. It never silently loads a partial set.

This satisfies the requirement that one arbitrary map is enough, including `control`, without silently adding telemetry or activating writing.

## Telemetry map

`telemetry.yaml` contains standard read-only telemetry expected to be available through Solarman TCP and Modbus RTU for the declared model family. It contains only entries with explicit compatibility evidence for both transports.

```yaml
format: 1
map_id: telemetry
catalog_set: deye_sg04_sg05_3ph_lv
purpose: telemetry
writable: false
transports: [solarman_tcp, modbus_rtu]
sensors:
  - key: battery_voltage
    name: Battery Voltage
    registers: [587]
    type: uint16
    multiplier: 0.01
    unit: V
    device_class: voltage
    state_class: measurement
    verification: documented
    sources: []
```

The existing 94-entry catalog is the candidate starting point. An entry must not move into this map simply because it works through the current Solarman logger.

## Telemetry+ map

`telemetry-plus.yaml` is read-only but Solarman-specific. It stores data available, reliable, or verified only through the logger transport.

```yaml
format: 1
map_id: telemetry_plus
catalog_set: deye_sg04_sg05_3ph_lv
purpose: telemetry_plus
writable: false
transports: [solarman_tcp]
sensors:
  - key: battery_{pack}_bms_serial
    name: Battery {pack} BMS Serial
    registers: [10032,10033,10034,10035,10036,10037,10038,10039]
    type: ascii
    byte_order: low_high
    verification: verified_local
    transport_note: Solarman BMS per-pack block
```

The BMS per-pack block at `10032+` belongs in this map until it is separately proven over direct RS485 for the exact model and firmware. A successful Solarman scan is not proof of RS485 availability.

## Control map

`control.yaml` is structurally different from telemetry. It contains no MQTT sensor definitions and no arbitrary writable register list. Each command is an auditable operation with encoding, validation, confirmation, and read-back.

```yaml
format: 1
map_id: control
catalog_set: deye_sg04_sg05_3ph_lv
purpose: control
writable: true
transports: [solarman_tcp, modbus_rtu]
commands:
  - id: example_command_only
    name: Example command only
    status: planned
    writable_registers: []
    readback_registers: []
    allowed_values: []
    confirmation: required
    cooldown_seconds: 0
    audit_level: blocked
```

No real writable register may be added until all of these are known and reviewed:

- model family and firmware scope;
- exact register address, Modbus function, word encoding, and byte order;
- allowed range, enum mapping, bit semantics, and dangerous values;
- precondition registers and expected state;
- read-back registers and expected response;
- transport support verified separately for Solarman TCP and RS485;
- confirmation wording, cooldown, rate limit, rollback behavior, source, and local verification state.

Runtime safety rules:

- `control.enabled` defaults to `false` and is independent from `selected_maps`.
- A user arms control in the panel only for a short session.
- Every write requires a second confirmation showing old and requested values.
- The add-on performs read-before-write, write, wait, read-back, then logs one structured audit record.
- Timeout or mismatched read-back disables further writes for the session.
- No bulk write, raw write console, formula write, or automatic write retry exists.
- MQTT control entities are published only after each command is separately validated and enabled.

Thus `control` can be the only selected map without creating an unsafe write path.

## MQTT identity and concurrent transports

The same inverter must not create colliding MQTT Discovery entities when both add-ons are installed. The default policy is exclusive MQTT publisher ownership per inverter serial number:

```yaml
mqtt:
  device_identity: deye_<inverter_serial>
  publisher_owner: solarman_tcp
```

The second add-on may scan and test locally, but MQTT publishing remains disabled until ownership is transferred. A future advanced mode may publish both only with distinct device identities and topic prefixes. It must never overwrite the first add-on's retained Discovery configuration.

## Evidence states

Each sensor and command declares an explicit status shown by the UI:

| Status | Meaning |
| --- | --- |
| `documented` | Supported by a cited protocol or manufacturer source. |
| `candidate` | Plausible entry, not semantically confirmed. |
| `verified_local` | Value and decoding compared with the local installation. |
| `transport_verified` | Verified on one named transport. |
| `unavailable` | Explicitly unavailable for the model or transport. |
| `blocked` | Not safe to expose or operate. |

A successful scan changes only the transport result for the current device. It does not automatically promote a `candidate` to `documented` or unlock a control command.

## Migration plan

1. Keep the released add-on and current version-2 catalog unchanged.
2. Extract transport-independent modules into `packages/deye_inverter_core` with behavior-preserving tests.
3. Add a bundle loader able to load one selected map and adapt it to the present scanner and MQTT code.
4. Convert entries to `telemetry.yaml` only after each has explicit transport classification.
5. Add `telemetry-plus.yaml` for logger-only data, beginning with the BMS block at `10032+`.
6. Add the RS485 add-on only after its transport suite proves the shared read interface.
7. Create an empty, blocked `control.yaml`; add commands individually with read-back tests and security review.
8. Add GHCR release builds, checksums, cache migration, and migration documentation for existing Solarman users.

## Sources

- Home Assistant supports one or more apps in one repository, each in its own unique folder: https://developers.home-assistant.io/docs/apps/repository/
- Home Assistant app configuration and per-app directory structure: https://developers.home-assistant.io/docs/apps/configuration/
- Home Assistant guidance for pre-built multi-architecture images: https://developers.home-assistant.io/docs/add-ons/publishing/
- Docker build context restricts `COPY` sources to files inside that context: https://github.com/docker-archive/docker-ce/blob/master/components/cli/docs/reference/builder.md
