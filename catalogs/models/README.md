# Model catalog sets in SolarMan Diagnostics 2.0.5

Each supported inverter family has its own directory, for example:

```text
deye_sg04_sg05_3ph_lv/
  catalog-index.yaml
  telemetry.yaml
  control.yaml
```

Map files are model-family specific. The runtime rejects a map whose compatibility metadata does not include the selected transport.

Every model directory must contain `catalog-index.yaml`. The index declares the stable `catalog_set`, revision, and available maps with their file names, SHA-256 checksums, transports, and write capability. The site generator discovers model directories automatically by locating and validating these index files.

The index may also declare:

- `display_name` - human-readable name shown in the register browser;
- `manufacturer` - inverter manufacturer;
- `model_families` - list of compatible model families.

Telemetry and control are independent. A valid index can expose only `telemetry`, only `control`, or both. Adding another model does not require editing the website source: place the model directory under `catalogs/models`, provide its valid index and referenced map files, then run the site generator.
