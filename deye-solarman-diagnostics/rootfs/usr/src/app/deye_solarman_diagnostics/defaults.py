from __future__ import annotations

from dataclasses import replace

from .catalog import build_bms_pack_sensors
from .models import SensorDefinition


DEFAULT_ENABLED_KEYS={
	"battery_1_voltage",
	"battery_1_current",
	"battery_1_temperature",
	"battery_1_soc",
}


def _default_battery_sensors() -> list[SensorDefinition]:
	return [
		replace(sensor, enabled=sensor.key in DEFAULT_ENABLED_KEYS)
		for sensor in build_bms_pack_sensors(4)
	]


DEFAULT_PROFILES: dict[str, list[SensorDefinition]]={
	"deye_battery_packs": _default_battery_sensors(),
}
