# Register catalogs in SolarMan Diagnostics 2.0.0

This directory is the canonical source for the checksummed catalog bundle used by the add-on runtime.

Maps are separated by purpose:

- `telemetry` - standard read-only registers for the transports declared by the map;
- `telemetry_plus` - extended read-only diagnostics;
- `control` - validated control definitions with read-back metadata.

`tools/package_addon.py` copies the selected model set and its `catalog-index.yaml` into the self-contained add-on rootfs. The compatible single-file telemetry URL at `deye-solarman-diagnostics/deye_sg04_sg05_3ph_lv_catalog.yaml` is generated from the same canonical maps for existing installations.
