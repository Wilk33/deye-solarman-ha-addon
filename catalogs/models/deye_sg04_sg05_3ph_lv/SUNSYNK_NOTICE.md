# Sunsynk control catalog attribution

The data in `control.yaml` is derived from kellerza/sunsynk, the Deye/Sunsynk Inverter Python library and Home Assistant OS Addon by Johann Kellerman and contributors.

Source revision: `e2466b6505c1990aced1f18c12a42ded638aee9b`.

Source: https://github.com/kellerza/sunsynk/tree/e2466b6505c1990aced1f18c12a42ded638aee9b/src/sunsynk

Upstream license: Apache License 2.0, reproduced in `SUNSYNK_LICENSE.txt`.

Modifications: writable definitions from the three-phase LV profile were exported into standalone JSON; aliases were excluded, sensor limits were represented as register dependencies, and keys were prefixed with `control_`. The add-on uses its own runtime implementation and does not execute upstream Python code.
