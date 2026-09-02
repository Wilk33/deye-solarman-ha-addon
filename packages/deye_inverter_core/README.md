# Deye Inverter Core

Reserved source location for the transport-independent Python package shared by the Solarman and RS485 applications.

The package will own register decoding, map validation, scan orchestration, scheduling, MQTT Discovery, persistent selections, custom sensors, formulas, the web panel, and structured logging. It must not import a Solarman TCP or Modbus RTU client directly.

Transport adapters will implement the common read interface documented in `docs/architecture/MULTI_ADDON_AND_CATALOGS.md`.
