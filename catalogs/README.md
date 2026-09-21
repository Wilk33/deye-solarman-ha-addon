# Register catalogs in SolarMan Diagnostics 2.0.5

- [Project site](https://wilk33.github.io/deye-solarman-ha-addon/)
- [Register reference](https://wilk33.github.io/deye-solarman-ha-addon/reference/)

This directory is the canonical source for the checksummed catalog bundle used by the add-on runtime.

Maps are separated by purpose and may be configured independently:

- `telemetry` - read-only registers and the BMS pack template;
- `control` - validated control definitions with read-back metadata.

The public register reference is generated from every valid model directory below `catalogs/models`. A model may provide only `telemetry`, only `control`, or both maps. Telemetry and control remain independent in the generated browser and in add-on configuration, so their files can be maintained or supplied separately.

`tools/package_addon.py` copies the selected model set and its `catalog-index.yaml` into the self-contained add-on rootfs. The compatible telemetry URL at `deye-solarman-diagnostics/deye_sg04_sg05_3ph_lv_catalog.yaml` is an exact generated copy of the canonical `telemetry.yaml` for existing installations.
