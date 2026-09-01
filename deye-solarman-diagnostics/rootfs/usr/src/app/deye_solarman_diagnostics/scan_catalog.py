from __future__ import annotations

from dataclasses import dataclass
from .catalog import build_bms_pack_sensors
from .catalog import build_live_telemetry
from .models import SensorDefinition
from .remote_catalog import RemoteCatalog
from .remote_catalog import apply_remote_catalog


@dataclass(frozen=True, slots=True)
class ScanCandidate:
	sensor: SensorDefinition
	verification: str
	description: str


def load_scan_candidates(bms_pack_count: int, remote_catalog: RemoteCatalog | None=None) -> list[ScanCandidate]:
	sensors=build_live_telemetry()+build_bms_pack_sensors(bms_pack_count)
	if remote_catalog is not None:
		sensors=apply_remote_catalog(sensors,remote_catalog)
	candidates=[
		ScanCandidate(
			sensor,
			"documented",
			"Read-only live telemetry documented for Deye SUN-SG04LP3 and SUN-SG05LP3 three-phase low-voltage hybrid inverters.",
		)
		for sensor in sensors
		if not _is_bms_sensor(sensor,bms_pack_count)
	]
	for sensor in sensors:
		if not _is_bms_sensor(sensor,bms_pack_count):
			continue
		verification="verified_local" if sensor.key == "battery_1_voltage" else "candidate"
		description=(
			"Confirmed by a successful local Solarman read on this installation."
			if verification == "verified_local"
			else "Per-pack BMS candidate. A successful read confirms transport access, not the semantic meaning of the register."
		)
		candidates.append(ScanCandidate(sensor, verification, description))
	return candidates


def _is_bms_sensor(sensor: SensorDefinition, bms_pack_count: int) -> bool:
	parts=sensor.key.split("_",2)
	return (
		len(parts) == 3
		and parts[0] == "battery"
		and parts[1].isdigit()
		and 1 <= int(parts[1]) <= bms_pack_count
	)
