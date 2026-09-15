from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .models import SensorDefinition
from .remote_catalog import RemoteCatalog
from .remote_catalog import _validate_payload
from .remote_catalog import apply_remote_catalog


CATALOG_FILENAME="deye_sg04_sg05_3ph_lv_catalog.yaml"


@lru_cache(maxsize=1)
def _packaged_catalog() -> RemoteCatalog:
	payload=_load_packaged_catalog_payload()
	_validate_payload(payload)
	return RemoteCatalog(
		payload["sensors"],
		"packaged",
		payload.get("bms_pack"),
		int(payload["version"]),
	)


def _load_packaged_catalog_payload() -> dict[str, Any]:
	from .catalog_bundle import legacy_telemetry_payload
	return legacy_telemetry_payload()


def build_live_telemetry() -> list[SensorDefinition]:
	return apply_remote_catalog([],_packaged_catalog())


def build_bms_pack_sensors(pack_count: int) -> list[SensorDefinition]:
	sensors=apply_remote_catalog([],_packaged_catalog(),pack_count)
	return [
		sensor
		for sensor in sensors
		if sensor.registers and min(sensor.registers) >= 10032
	]
