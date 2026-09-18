# Model catalog sets in SolarMan Diagnostics 2.0.1

Each supported inverter family has its own directory, for example:

```text
deye_sg04_sg05_3ph_lv/
  catalog-index.yaml
  telemetry.yaml
  telemetry-plus.yaml
  control.yaml
```

Map files are model-family specific. The runtime rejects a map whose compatibility metadata does not include the selected transport.
