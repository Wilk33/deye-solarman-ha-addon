# Deye SG04LP3 and SG05LP3 Three-Phase LV - SolarMan Diagnostics 2.0.4

This is the canonical catalog set bundled into the add-on.

Map files:

- `catalog-index.yaml` - immutable release manifest and checksums.
- `telemetry.yaml` - read-only values and the BMS pack template supported by SolarMan TCP and RS485.
- `control.yaml` - validated commands with read-before-write and read-back.

`catalog-index.yaml` declares revision 2.0.4, transport compatibility and SHA-256 checksums. The packaging tool also generates the compatible telemetry catalog at `../../../../deye-solarman-diagnostics/deye_sg04_sg05_3ph_lv_catalog.yaml` as an exact copy of `telemetry.yaml`.
