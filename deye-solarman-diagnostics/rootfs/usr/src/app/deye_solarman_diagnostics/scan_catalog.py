from __future__ import annotations

from dataclasses import dataclass
from .catalog import build_bms_pack_sensors
from .catalog import build_live_telemetry
from .models import SensorDefinition


@dataclass(frozen=True, slots=True)
class ScanCandidate:
	sensor: SensorDefinition
	verification: str
	description: str


def load_scan_candidates(bms_pack_count: int) -> list[ScanCandidate]:
	candidates=[
		ScanCandidate(
			sensor,
			"documented",
			"Read-only live telemetry documented for Deye SUN-SG04LP3 and SUN-SG05LP3 three-phase low-voltage hybrid inverters.",
		)
		for sensor in build_live_telemetry()
	]
	for sensor in build_bms_pack_sensors(bms_pack_count):
		verification="verified_local" if sensor.key == "battery_1_voltage" else "candidate"
		description=(
			"Confirmed by a successful local Solarman read on this installation."
			if verification == "verified_local"
			else "Per-pack BMS candidate. A successful read confirms transport access, not the semantic meaning of the register."
		)
		candidates.append(ScanCandidate(sensor, verification, description))
	return candidates
