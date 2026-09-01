from __future__ import annotations

from dataclasses import asdict
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from .defaults import DEFAULT_PROFILES
from .formula import validate_formula
from .models import SensorDefinition
from .scanner import load_monitored_definitions


SUPPORTED_REGISTER_TYPES={"uint16","int16","uint32","int32","hex","ascii"}
FORMULA_REGISTER_TYPE="auto"


def load_sensor_definitions(
	profile_names: list[str],
	overrides_file: str,
	detected_sensors_file: str | None=None,
	custom_sensors_file: str | None=None,
) -> list[SensorDefinition]:
	unknown_profiles=[name for name in profile_names if name not in DEFAULT_PROFILES]
	if unknown_profiles:
		raise ValueError(f"Unknown sensor profile(s): {', '.join(unknown_profiles)}")

	sensors: list[SensorDefinition]=[]
	for profile_name in profile_names:
		sensors.extend(replace(sensor) for sensor in DEFAULT_PROFILES.get(profile_name,[]))

	merged=_apply_overrides(sensors, Path(overrides_file), detected_sensors_file)
	if custom_sensors_file:
		merged.extend(load_custom_sensor_definitions(custom_sensors_file))
	return _validate_sensor_definitions(merged)


def load_custom_sensor_definitions(path: str) -> list[SensorDefinition]:
	from .custom_sensors import load_custom_sensors

	payload=load_custom_sensors(path)
	entries=payload.get("sensors",[])
	if not isinstance(entries,list):
		raise ValueError("custom_sensors.yaml: sensors must be a list")
	sensors=[]
	for index, entry in enumerate(entries):
		if not isinstance(entry,dict):
			raise ValueError(f"custom_sensors.yaml: sensors[{index}] must be an object")
		monitor=entry.get("monitor",True)
		if not isinstance(monitor,bool):
			raise ValueError(f"custom_sensors.yaml: sensors[{index}].monitor must be a boolean")
		definition=entry.get("definition")
		if not isinstance(definition,dict):
			raise ValueError(f"custom_sensors.yaml: sensors[{index}].definition must be an object")
		if definition.get("key") != entry.get("key"):
			raise ValueError(f"custom_sensors.yaml: sensors[{index}] has inconsistent key")
		sensors.append(sensor_from_payload(definition,enabled=monitor))
	return _validate_sensor_definitions(sensors)


def _apply_overrides(
	defaults: list[SensorDefinition],
	overrides_path: Path,
	detected_sensors_file: str | None,
) -> list[SensorDefinition]:
	overrides={
		item["key"]: item
		for item in _load_monitored_items(detected_sensors_file)
	}
	overrides.update(_load_override_items(overrides_path))
	merged: list[SensorDefinition]=[]

	for sensor in defaults:
		override=overrides.get(sensor.key)
		if not override:
			merged.append(sensor)
			continue
		data=asdict(sensor)
		for key, value in override.items():
			if key == "type":
				data["register_type"]=value
			elif key in data:
				data[key]=value
		merged.append(SensorDefinition(**data))

	for key, override in overrides.items():
		if any(sensor.key == key for sensor in merged):
			continue
		merged.append(_sensor_from_override(override))

	return merged


def _load_override_items(overrides_path: Path) -> dict[str, dict[str, Any]]:
	if not overrides_path.exists():
		return {}
	with overrides_path.open("r", encoding="utf-8") as handle:
		payload=yaml.safe_load(handle) or {}
	if not isinstance(payload, dict):
		raise ValueError("user_sensors.yaml: root value must be an object")
	override_items=payload.get("sensors",[])
	if not isinstance(override_items, list):
		raise ValueError("user_sensors.yaml: sensors must be a list")

	overrides: dict[str, dict[str, Any]]={}
	for index, item in enumerate(override_items):
		if not isinstance(item, dict) or not isinstance(item.get("key"), str) or not item["key"]:
			raise ValueError(f"user_sensors.yaml: sensors[{index}].key must be a non-empty string")
		overrides[item["key"]]=item
	return overrides


def _load_monitored_items(detected_sensors_file: str | None) -> list[dict[str, Any]]:
	if not detected_sensors_file:
		return []
	items=load_monitored_definitions(detected_sensors_file)
	for index, item in enumerate(items):
		if not isinstance(item.get("key"), str) or not item["key"]:
			raise ValueError(f"detected_sensors.yaml: selected definition {index} has an invalid key")
	return items


def _validate_sensor_definitions(sensors: list[SensorDefinition]) -> list[SensorDefinition]:
	if not sensors:
		raise ValueError("No sensor definitions are configured")

	keys: set[str]=set()
	for sensor in sensors:
		if not sensor.key or sensor.key in keys:
			raise ValueError(f"Sensor key must be unique and non-empty: {sensor.key!r}")
		keys.add(sensor.key)
		if sensor.register_type not in SUPPORTED_REGISTER_TYPES:
			if sensor.register_type != FORMULA_REGISTER_TYPE or not sensor.formula:
				raise ValueError(f"Sensor {sensor.key}: unsupported type {sensor.register_type!r}")
		if sensor.formula:
			if sensor.register_type != FORMULA_REGISTER_TYPE:
				raise ValueError(f"Sensor {sensor.key}: formula requires type auto")
			if sensor.registers:
				raise ValueError(f"Sensor {sensor.key}: formula cannot declare direct registers")
			validate_formula(sensor.formula)
		else:
			if not sensor.registers or any(type(register) is not int or register < 0 or register > 65535 for register in sensor.registers):
				raise ValueError(f"Sensor {sensor.key}: registers must contain values from 0 to 65535")
			if sensor.register_type in {"uint16","int16"} and len(sensor.registers) != 1:
				raise ValueError(f"Sensor {sensor.key}: {sensor.register_type} requires exactly one register")
			if sensor.register_type in {"uint32","int32"} and len(sensor.registers) != 2:
				raise ValueError(f"Sensor {sensor.key}: {sensor.register_type} requires exactly two registers")
		if sensor.word_order not in {"high_low","low_high"}:
			raise ValueError(f"Sensor {sensor.key}: unsupported word_order {sensor.word_order!r}")
		if sensor.schedule not in {"default","slow"}:
			raise ValueError(f"Sensor {sensor.key}: unsupported schedule {sensor.schedule!r}")
		if sensor.read_every <= 0 or sensor.report_every <= 0 or sensor.change_by < 0:
			raise ValueError(f"Sensor {sensor.key}: read_every and report_every must be positive, change_by cannot be negative")

	return sensors


def sensor_from_payload(payload: dict[str, Any], enabled: bool=True) -> SensorDefinition:
	formula=payload.get("formula","")
	if not isinstance(formula,str):
		raise ValueError("Sensor formula must be text")
	registers=payload.get("registers",[] if formula else None)
	if not isinstance(registers,list):
		raise ValueError("Sensor registers must be a list")
	return SensorDefinition(
		key=payload["key"],
		name=payload.get("name", payload["key"].replace("_"," ").title()),
		registers=list(registers),
		register_type=payload.get("type",FORMULA_REGISTER_TYPE if formula else "uint16"),
		multiplier=float(payload.get("multiplier",1.0)),
		offset=float(payload.get("offset",0.0)),
		unit=payload.get("unit",""),
		word_order=payload.get("word_order","high_low"),
		schedule=payload.get("schedule","default"),
		read_every=int(payload.get("read_every",60)),
		report_every=int(payload.get("report_every",300)),
		change_by=float(payload.get("change_by",0.0)),
		enabled=enabled,
		retain=bool(payload.get("retain",True)),
		device_class=payload.get("device_class",""),
		state_class=payload.get("state_class",""),
		icon=payload.get("icon",""),
		category=payload.get("category",""),
		topic_suffix=payload.get("topic_suffix",payload["key"]),
		formula=formula,
		attributes=dict(payload.get("attributes",{})),
	)


def _sensor_from_override(payload: dict[str, Any]) -> SensorDefinition:
	return sensor_from_payload(payload,enabled=bool(payload.get("enabled",True)))
