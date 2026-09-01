from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .definitions import sensor_from_payload
from .definitions import _validate_sensor_definitions
from .scanner import _queue_discovery_removal_keys


def load_custom_sensors(path: str) -> dict[str, Any]:
	target=Path(path)
	if not target.exists():
		return {"version": 1,"sensors": []}
	return _load_yaml_mapping(target)


def save_custom_sensors(path: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
	target=Path(path)
	target.parent.mkdir(parents=True,exist_ok=True)
	if not isinstance(entries,list):
		raise ValueError("custom sensors must be a list")
	previous=load_custom_sensors(path)
	previous_entries={
		entry.get("key"): entry
		for entry in previous.get("sensors",[])
		if isinstance(entry,dict) and isinstance(entry.get("key"),str)
	}
	validated=[]
	seen: set[str]=set()
	for index, entry in enumerate(entries):
		if not isinstance(entry,dict):
			raise ValueError(f"custom sensors[{index}] must be an object")
		key=entry.get("key")
		monitor=entry.get("monitor",True)
		definition=entry.get("definition")
		if not isinstance(key,str) or not key or key in seen:
			raise ValueError(f"custom sensors[{index}].key must be unique and non-empty")
		if not isinstance(monitor,bool):
			raise ValueError(f"custom sensor {key}: monitor must be a boolean")
		if not isinstance(definition,dict):
			raise ValueError(f"custom sensor {key}: definition must be an object")
		if definition.get("key") != key:
			raise ValueError(f"custom sensor {key}: definition key is inconsistent")
		sensor=sensor_from_payload(definition,enabled=monitor)
		_validate_sensor_definitions([sensor])
		validated.append({"key": key,"monitor": monitor,"definition": _normalized_definition(sensor)})
		seen.add(key)

	removed={
		key
		for key, entry in previous_entries.items()
		if entry.get("monitor") is True and (
			key not in seen or not next(item["monitor"] for item in validated if item["key"] == key)
		)
	}
	_queue_discovery_removal_keys(target,removed)
	payload={"version": 1,"sensors": validated}
	_write_yaml(target,payload)
	return payload


def delete_custom_sensor(path: str, key: str) -> dict[str, Any]:
	payload=load_custom_sensors(path)
	entries=payload.get("sensors",[])
	if not isinstance(entries,list):
		raise ValueError("custom_sensors.yaml: sensors must be a list")
	if not any(isinstance(entry,dict) and entry.get("key") == key for entry in entries):
		raise ValueError(f"Custom sensor does not exist: {key}")
	remaining=[entry for entry in entries if isinstance(entry,dict) and entry.get("key") != key]
	return save_custom_sensors(path,remaining)


def _normalized_definition(sensor: Any) -> dict[str, Any]:
	return {
		"key": sensor.key,
		"name": sensor.name,
		"registers": sensor.registers,
		"type": sensor.register_type,
		"multiplier": sensor.multiplier,
		"offset": sensor.offset,
		"unit": sensor.unit,
		"word_order": sensor.word_order,
		"schedule": sensor.schedule,
		"read_every": sensor.read_every,
		"report_every": sensor.report_every,
		"change_by": sensor.change_by,
		"retain": sensor.retain,
		"device_class": sensor.device_class,
		"state_class": sensor.state_class,
		"icon": sensor.icon,
		"category": sensor.category,
		"topic_suffix": sensor.topic_suffix,
		"formula": sensor.formula,
	}


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
	try:
		with path.open("r",encoding="utf-8") as handle:
			payload=yaml.safe_load(handle) or {}
	except (OSError,yaml.YAMLError) as error:
		raise ValueError(f"Unable to read {path}: {error}") from error
	if not isinstance(payload,dict):
		raise ValueError(f"{path.name}: root value must be an object")
	return payload


def _write_yaml(target: Path, payload: dict[str, Any]) -> None:
	temporary=target.with_name(f".{target.name}.tmp")
	with temporary.open("w",encoding="utf-8") as handle:
		yaml.safe_dump(payload,handle,allow_unicode=False,sort_keys=False)
	temporary.replace(target)
