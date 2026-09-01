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
from .codec import registers_to_ascii
from .models import PollingConfig
from .scan_catalog import ScanCandidate
from .scheduler import group_sensors_for_read
from .solarman import SolarmanClientProtocol


EDITABLE_DEFINITION_FIELDS={
	"name",
	"type",
	"multiplier",
	"offset",
	"unit",
	"word_order",
	"byte_order",
	"schedule",
	"read_every",
	"report_every",
	"change_by",
	"retain",
	"device_class",
	"state_class",
	"icon",
	"category",
	"topic_suffix",
}


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
			# Existing files predate byte_order, so retain user settings while applying the new BMS serial default.
			if key.endswith("_bms_serial") and "byte_order" not in previous_definition:
				definition["byte_order"]="low_high"
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
					"raw_ascii": result.get("raw_ascii",""),
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


def reset_detected_sensors(path: str, candidates: list[ScanCandidate]) -> dict[str, Any]:
	"""Restore catalog defaults for sensors already found by a scan."""
	target=Path(path)
	payload=load_detected_sensors(path)
	entries=payload.get("available_sensors",[])
	if not isinstance(entries,list):
		raise ValueError("detected_sensors.yaml: available_sensors must be a list")

	_queue_discovery_removals(target,entries)
	defaults={candidate.sensor.key: _sensor_to_payload(candidate.sensor) for candidate in candidates}
	reset_entries=[]
	for entry in entries:
		if not isinstance(entry,dict):
			continue
		key=entry.get("key")
		if not isinstance(key,str) or key not in defaults:
			continue
		reset_entries.append(
			{
				"key": key,
				"monitor": False,
				"definition": defaults[key],
				"last_scan": entry.get("last_scan",{}),
			}
		)

	payload["available_sensors"]=reset_entries
	_write_yaml(target,payload)
	return payload


def clear_detected_sensors(path: str) -> dict[str, Any]:
	"""Remove all local scan results and their per-sensor configuration."""
	target=Path(path)
	target.parent.mkdir(parents=True,exist_ok=True)
	previous=load_detected_sensors(path)
	entries=previous.get("available_sensors",[])
	if isinstance(entries,list):
		_queue_discovery_removals(target,entries)
	payload={
		"version": 1,
		"scanned_at": None,
		"available_sensors": [],
	}
	_write_yaml(target,payload)
	return payload


def load_pending_discovery_removals(path: str) -> list[str]:
	payload=_load_yaml_mapping(_discovery_removals_path(Path(path)))
	keys=payload.get("keys",[])
	if not isinstance(keys,list) or not all(isinstance(key,str) and key for key in keys):
		raise ValueError("discovery removal queue: keys must be a list of sensor keys")
	return keys


def clear_pending_discovery_removals(path: str) -> None:
	target=_discovery_removals_path(Path(path))
	if target.exists():
		target.unlink()


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


def load_detected_sensors(path: str) -> dict[str, Any]:
	target=Path(path)
	if not target.exists():
		return {
			"version": 1,
			"scanned_at": None,
			"available_sensors": [],
		}
	return _load_yaml_mapping(target)


def update_detected_sensors(path: str, updates: list[dict[str, Any]]) -> dict[str, Any]:
	target=Path(path)
	payload=load_detected_sensors(path)
	entries=payload.get("available_sensors")
	if not isinstance(entries, list):
		raise ValueError("detected_sensors.yaml: available_sensors must be a list")
	entries_by_key={
		entry.get("key"): entry
		for entry in entries
		if isinstance(entry, dict) and isinstance(entry.get("key"), str)
	}

	removed_keys: set[str]=set()
	for index, update in enumerate(updates):
		if not isinstance(update, dict):
			raise ValueError(f"Update {index} must be an object")
		key=update.get("key")
		if not isinstance(key, str) or key not in entries_by_key:
			raise ValueError(f"Update {index} has an unknown sensor key")
		entry=entries_by_key[key]
		monitor=update.get("monitor")
		if not isinstance(monitor, bool):
			raise ValueError(f"Update {key}: monitor must be a boolean")
		definition_update=update.get("definition",{})
		if not isinstance(definition_update, dict):
			raise ValueError(f"Update {key}: definition must be an object")
		definition=entry.get("definition")
		if not isinstance(definition, dict):
			raise ValueError(f"detected_sensors.yaml: {key} has no definition")

		if entry.get("monitor") is True and not monitor:
			removed_keys.add(key)
		entry["monitor"]=monitor
		for field, value in definition_update.items():
			if field not in EDITABLE_DEFINITION_FIELDS:
				continue
			definition[field]=_validate_definition_value(key, field, value)

	_queue_discovery_removal_keys(target,removed_keys)
	_write_yaml(target, payload)
	return payload


def _scan_value(
	candidate: ScanCandidate,
	group_values: list[int],
	group_start: int,
	latency_ms: float,
) -> dict[str, Any]:
	sensor=candidate.sensor
	try:
		raw_values=[group_values[register-group_start] for register in sensor.registers]
		decoded=decode_registers(raw_values,sensor.register_type,sensor.word_order,sensor.byte_order)
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
		"raw_ascii": registers_to_ascii(raw_values,sensor.byte_order),
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
		"raw_ascii": "",
		"latency_ms": round(latency_ms,2) if latency_ms is not None else None,
		"error": error,
		"verification": candidate.verification,
		"description": candidate.description,
	}


def _sensor_to_payload(sensor: Any) -> dict[str, Any]:
	payload=asdict(sensor)
	payload["type"]=payload.pop("register_type")
	return payload


def _validate_definition_value(key: str, field: str, value: Any) -> Any:
	if field in {"name","unit","device_class","state_class","icon","category","topic_suffix"}:
		if not isinstance(value, str):
			raise ValueError(f"Update {key}: {field} must be text")
		return value.strip()
	if field in {"multiplier","offset","change_by"}:
		if isinstance(value, bool):
			raise ValueError(f"Update {key}: {field} must be a number")
		try:
			parsed=float(value)
		except (TypeError, ValueError) as error:
			raise ValueError(f"Update {key}: {field} must be a number") from error
		if field == "change_by" and parsed < 0:
			raise ValueError(f"Update {key}: change_by cannot be negative")
		return parsed
	if field in {"read_every","report_every"}:
		if isinstance(value, bool):
			raise ValueError(f"Update {key}: {field} must be a positive integer")
		try:
			parsed=int(value)
		except (TypeError, ValueError) as error:
			raise ValueError(f"Update {key}: {field} must be a positive integer") from error
		if parsed <= 0:
			raise ValueError(f"Update {key}: {field} must be a positive integer")
		return parsed
	if field == "retain":
		if not isinstance(value, bool):
			raise ValueError(f"Update {key}: retain must be a boolean")
		return value
	if field == "type":
		if value not in {"uint16","int16","uint32","int32","hex","ascii"}:
			raise ValueError(f"Update {key}: unsupported type")
		return value
	if field == "word_order":
		if value not in {"high_low","low_high"}:
			raise ValueError(f"Update {key}: unsupported word order")
		return value
	if field == "byte_order":
		if value not in {"high_low","low_high"}:
			raise ValueError(f"Update {key}: unsupported byte order")
		return value
	if field == "schedule":
		if value not in {"default","slow"}:
			raise ValueError(f"Update {key}: unsupported schedule")
		return value
	raise ValueError(f"Update {key}: unsupported field {field}")


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


def _queue_discovery_removals(target: Path, entries: list[Any]) -> None:
	keys={
		entry.get("key")
		for entry in entries
		if isinstance(entry,dict) and entry.get("monitor") is True and isinstance(entry.get("key"),str)
	}
	_queue_discovery_removal_keys(target,keys)


def _queue_discovery_removal_keys(target: Path, keys: set[str]) -> None:
	if not keys:
		return
	queue_path=_discovery_removals_path(target)
	payload=_load_yaml_mapping(queue_path)
	pending=payload.get("keys",[])
	if not isinstance(pending,list):
		pending=[]
	keys.update(key for key in pending if isinstance(key,str) and key)
	_write_yaml(queue_path,{"version": 1,"keys": sorted(keys)})


def _discovery_removals_path(target: Path) -> Path:
	return target.with_name("deye_solarman_discovery_removals.yaml")
