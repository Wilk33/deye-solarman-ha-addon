# Deye Solarman Local

Canonical application source for the local Solarman TCP add-on, version 1.2.0.

`src/deye_solarman_diagnostics` contains only the entry point and Solarman adapter. The entry point injects the adapter into `deye_inverter_core.main`. Read and write operations implement the shared transport contracts.

HAOS installation remains in `../../deye-solarman-diagnostics/` with its existing slug and configuration, preserving the update path. `tools/package_addon.py` generates its self-contained build context from this application, the shared core and the model catalogs. Do not edit generated runtime copies.
