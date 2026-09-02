# Applications

This directory is reserved for future Home Assistant applications.

Do not add `config.yaml` here until an application is complete and installable. Home Assistant Supervisor searches the repository for application configuration files, so an unfinished application could otherwise appear in the store.

Planned applications:

- `deye-solarman` - local read/write access through a Solarman TCP logger.
- `deye-rs485` - direct local Modbus RTU access through USB-RS485.

The currently released application remains in `deye-solarman-diagnostics/` until the compatibility-preserving migration described in `docs/architecture/MULTI_ADDON_AND_CATALOGS.md` is implemented.
