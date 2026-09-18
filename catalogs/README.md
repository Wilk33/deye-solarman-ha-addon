# Register catalogs in SolarMan Diagnostics 2.0.4

This directory is the canonical source for the checksummed catalog bundle used by the add-on runtime.

Maps are separated by purpose and may be configured independently:

- `telemetry` - read-only registers and the BMS pack template;
- `control` - validated control definitions with read-back metadata.

`tools/package_addon.py` copies the selected model set and its `catalog-index.yaml` into the self-contained add-on rootfs. The compatible telemetry URL at `deye-solarman-diagnostics/deye_sg04_sg05_3ph_lv_catalog.yaml` is an exact generated copy of the canonical `telemetry.yaml` for existing installations.
