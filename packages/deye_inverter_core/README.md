# Deye Inverter Core

Canonical source of the shared Python core used by SolarMan Diagnostics 2.0.5.

The package owns register decoding, catalog loading, scan orchestration, scheduling, MQTT Discovery, persistent selections, custom sensors, formulas, controls, the web panel, and logging. It imports no Solarman TCP or Modbus RTU client. The application injects its transport factory into `main()`; contracts are in `transport.py`.

Run `python tools/package_addon.py` after source changes. The compatibility add-on contains generated copies; CI checks them with `--check`. Catalog sources live in `catalogs/models/deye_sg04_sg05_3ph_lv` and are packaged with SHA-256 checksums.
