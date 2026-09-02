# Register Catalogs

This directory is reserved for the future versioned catalog bundle format. The released Solarman application continues to use its compatible single-file catalog at:

`deye-solarman-diagnostics/deye_sg04_sg05_3ph_lv_catalog.yaml`

The future format separates maps by purpose:

- `telemetry` - standard read-only registers available through Solarman TCP and RS485.
- `telemetry_plus` - read-only registers exposed only through a Solarman logger.
- `control` - explicitly declared Modbus write operations with read-back and safety metadata.

No map is active from this directory yet. The migration is intentionally deferred until the new bundle loader is implemented and tested.
