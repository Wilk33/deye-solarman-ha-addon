from __future__ import annotations

from dataclasses import asdict
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from .defaults import DEFAULT_PROFILES
from .models import SensorDefinition


SUPPORTED_REGISTER_TYPES={"uint16","int16","uint32","int32","hex"}


def load_sensor_definitions(profile_names: list[str], overrides_file: str) -> list[SensorDefinition]:
	unknown_profiles=[name for name in profile_names if name not in DEFAULT_PROFILES]
	if unknown_profiles:
		raise ValueError(f"Unknown sensor profile(s): {', '.join(unknown_profiles)}")

	sensors: list[SensorDefinition]=[]
	for profile_name in profile_names:
		sensors.extend(replace(sensor) for sensor in DEFAULT_PROFILES.get(profile_name,[]))

	return _validate_sensor_definitions(_apply_overrides(sensors, Path(overrides_file)))


def _apply_overrides(defaults: list[SensorDefinition], overrides_path: Path) -> list[SensorDefinition]:
	if not overrides_path.exists():
		return defaults

	with overrides_path.open("r", encoding="utf-8") as handle:
		payload=yaml.safe_load(handle) or {}

	override_items=payload.get("sensors",[])
	if not isinstance(override_items, list):
		raise ValueError("user_sensors.yaml: sensors must be a list")

	overrides: dict[str, dict[str, Any]]={}
	for index, item in enumerate(override_items):
		if not isinstance(item, dict) or not isinstance(item.get("key"), str) or not item["key"]:
			raise ValueError(f"user_sensors.yaml: sensors[{index}].key must be a non-empty string")
		overrides[item["key"]]=item
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


def _validate_sensor_definitions(sensors: list[SensorDefinition]) -> list[SensorDefinition]:
	if not sensors:
		raise ValueError("No sensor definitions are configured")

	keys: set[str]=set()
	for sensor in sensors:
		if not sensor.key or sensor.key in keys:
			raise ValueError(f"Sensor key must be unique and non-empty: {sensor.key!r}")
		keys.add(sensor.key)
		if sensor.register_type not in SUPPORTED_REGISTER_TYPES:
			raise ValueError(f"Sensor {sensor.key}: unsupported type {sensor.register_type!r}")
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


def _sensor_from_override(payload: dict[str, Any]) -> SensorDefinition:
	return SensorDefinition(
		key=payload["key"],
		name=payload.get("name", payload["key"].replace("_"," ").title()),
		registers=list(payload["registers"]),
		register_type=payload.get("type","uint16"),
		multiplier=float(payload.get("multiplier",1.0)),
		offset=float(payload.get("offset",0.0)),
		unit=payload.get("unit",""),
		word_order=payload.get("word_order","high_low"),
		schedule=payload.get("schedule","default"),
		read_every=int(payload.get("read_every",60)),
		report_every=int(payload.get("report_every",300)),
		change_by=float(payload.get("change_by",0.0)),
		enabled=bool(payload.get("enabled",True)),
		retain=bool(payload.get("retain",True)),
		device_class=payload.get("device_class",""),
		state_class=payload.get("state_class",""),
		icon=payload.get("icon",""),
		category=payload.get("category",""),
		topic_suffix=payload.get("topic_suffix",payload["key"]),
		attributes=dict(payload.get("attributes",{})),
	)
