from __future__ import annotations

from dataclasses import replace

from .catalog import build_bms_pack_sensors
from .models import SensorDefinition


def _default_battery_sensors() -> list[SensorDefinition]:
	return [replace(sensor, enabled=False) for sensor in build_bms_pack_sensors(4)]


DEFAULT_PROFILES: dict[str, list[SensorDefinition]]={
	"deye_battery_packs": _default_battery_sensors(),
}
