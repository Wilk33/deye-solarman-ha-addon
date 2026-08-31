from __future__ import annotations

import time
from dataclasses import asdict
from dataclasses import replace
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .codec import apply_transform
from .codec import decode_registers
from .models import PollingConfig
from .scan_catalog import ScanCandidate
from .scheduler import group_sensors_for_read
from .solarman import SolarmanClientProtocol


def scan_candidates(
	candidates: list[ScanCandidate],
	solarman: SolarmanClientProtocol,
	polling: PollingConfig,
) -> list[dict[str, Any]]:
	by_key={candidate.sensor.key: candidate for candidate in candidates}
	readable=[replace(candidate.sensor, enabled=True) for candidate in candidates]
	report: list[dict[str, Any]]=[]
	groups=group_sensors_for_read(readable, polling)

	for index, group in enumerate(groups):
		group_start=min(register for sensor in group for register in sensor.registers)
		group_end=max(register for sensor in group for register in sensor.registers)
		count=group_end-group_start+1

		try:
			start=time.perf_counter()
			values=solarman.read_holding_registers(group_start, count)
			latency_ms=(time.perf_counter()-start)*1000
		except Exception as error:
			status=_read_error_status(error)
			for sensor in group:
				report.append(_scan_error(by_key[sensor.key], status, str(error)))
		else:
			for sensor in group:
				report.append(_scan_value(by_key[sensor.key], values, group_start, latency_ms))

		if index < len(groups)-1 and polling.read_message_spacing > 0:
			time.sleep(polling.read_message_spacing)

	return report


def _read_error_status(error: Exception) -> str:
	message=str(error).lower()
	unsupported_markers=(
		"illegal data address",
		"illegal function",
		"modbus exception",
		"exception response",
		"exception code",
	)
	if any(marker in message for marker in unsupported_markers):
		return "unsupported"
	return "timeout"


def save_detected_sensors(path: str, report: list[dict[str, Any]]) -> None:
	target=Path(path)
	target.parent.mkdir(parents=True, exist_ok=True)
	previous=_load_yaml_mapping(target)
	previous_entries={
		entry.get("key"): entry
		for entry in previous.get("available_sensors", [])
		if isinstance(entry, dict) and isinstance(entry.get("key"), str)
	}
	entries=[]

	for result in report:
		key=result["key"]
		previous_entry=previous_entries.get(key,{})
		definition=dict(result["definition"])
		previous_definition=previous_entry.get("definition")
		if isinstance(previous_definition, dict):
			definition.update(previous_definition)
		definition["key"]=key

		monitor=previous_entry.get("monitor",False)
		if not isinstance(monitor, bool):
			monitor=False
		entries.append(
			{
				"key": key,
				"monitor": monitor,
				"definition": definition,
				"last_scan": {
					"status": result["status"],
					"raw_registers": result.get("raw_registers",[]),
					"raw_hex": result.get("raw_hex",[]),
					"decoded": result.get("decoded"),
					"value": result.get("value"),
					"latency_ms": result.get("latency_ms"),
					"error": result.get("error"),
					"verification": result["verification"],
					"description": result["description"],
				},
			}
		)

	payload={
		"version": 1,
		"scanned_at": datetime.now(UTC).isoformat(),
		"available_sensors": entries,
	}
	_write_yaml(target, payload)


def load_monitored_definitions(path: str) -> list[dict[str, Any]]:
	target=Path(path)
	if not target.exists():
		return []
	payload=_load_yaml_mapping(target)
	entries=payload.get("available_sensors",[])
	if not isinstance(entries, list):
		raise ValueError("detected_sensors.yaml: available_sensors must be a list")

	definitions=[]
	for index, entry in enumerate(entries):
		if not isinstance(entry, dict):
			raise ValueError(f"detected_sensors.yaml: available_sensors[{index}] must be an object")
		monitor=entry.get("monitor",False)
		if not isinstance(monitor, bool):
			raise ValueError(f"detected_sensors.yaml: available_sensors[{index}].monitor must be a boolean")
		if not monitor:
			continue
		definition=entry.get("definition")
		if not isinstance(definition, dict):
			raise ValueError(f"detected_sensors.yaml: available_sensors[{index}].definition must be an object")
		if definition.get("key") != entry.get("key"):
			raise ValueError(f"detected_sensors.yaml: available_sensors[{index}] has inconsistent key")
		selected=dict(definition)
		selected["enabled"]=True
		definitions.append(selected)

	return definitions


def _scan_value(
	candidate: ScanCandidate,
	group_values: list[int],
	group_start: int,
	latency_ms: float,
) -> dict[str, Any]:
	sensor=candidate.sensor
	try:
		raw_values=[group_values[register-group_start] for register in sensor.registers]
		decoded=decode_registers(raw_values, sensor.register_type, sensor.word_order)
		value=apply_transform(decoded, sensor.multiplier, sensor.offset)
	except (IndexError, TypeError, ValueError) as error:
		return _scan_error(candidate, "invalid_value", str(error), latency_ms)

	return {
		"key": sensor.key,
		"name": sensor.name,
		"definition": _sensor_to_payload(sensor),
		"status": "supported",
		"raw_registers": raw_values,
		"raw_hex": [f"0x{value:04X}" for value in raw_values],
		"decoded": decoded,
		"value": value,
		"latency_ms": round(latency_ms,2),
		"verification": candidate.verification,
		"description": candidate.description,
	}


def _scan_error(
	candidate: ScanCandidate,
	status: str,
	error: str,
	latency_ms: float | None=None,
) -> dict[str, Any]:
	sensor=candidate.sensor
	return {
		"key": sensor.key,
		"name": sensor.name,
		"definition": _sensor_to_payload(sensor),
		"status": status,
		"raw_registers": [],
		"raw_hex": [],
		"latency_ms": round(latency_ms,2) if latency_ms is not None else None,
		"error": error,
		"verification": candidate.verification,
		"description": candidate.description,
	}


def _sensor_to_payload(sensor: Any) -> dict[str, Any]:
	payload=asdict(sensor)
	payload["type"]=payload.pop("register_type")
	return payload


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
	if not path.exists():
		return {}
	try:
		with path.open("r", encoding="utf-8") as handle:
			payload=yaml.safe_load(handle) or {}
	except (OSError, yaml.YAMLError) as error:
		raise ValueError(f"Unable to read {path}: {error}") from error
	if not isinstance(payload, dict):
		raise ValueError(f"{path.name}: root value must be an object")
	return payload


def _write_yaml(target: Path, payload: dict[str, Any]) -> None:
	temporary=target.with_name(f".{target.name}.tmp")
	with temporary.open("w", encoding="utf-8") as handle:
		yaml.safe_dump(payload, handle, allow_unicode=False, sort_keys=False)
	temporary.replace(target)
