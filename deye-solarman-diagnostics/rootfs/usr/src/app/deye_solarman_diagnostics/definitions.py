from __future__ import annotations

from dataclasses import asdict
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from .defaults import DEFAULT_PROFILES
from .models import SensorDefinition


def load_sensor_definitions(profile_names: list[str], overrides_file: str) -> list[SensorDefinition]:
	sensors: list[SensorDefinition]=[]
	for profile_name in profile_names:
		sensors.extend(replace(sensor) for sensor in DEFAULT_PROFILES.get(profile_name,[]))

	return _apply_overrides(sensors, Path(overrides_file))


def _apply_overrides(defaults: list[SensorDefinition], overrides_path: Path) -> list[SensorDefinition]:
	if not overrides_path.exists():
		return defaults

	with overrides_path.open("r", encoding="utf-8") as handle:
		payload=yaml.safe_load(handle) or {}

	overrides={item["key"]: item for item in payload.get("sensors",[])}
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
		read_every=int(payload.get("read_every",60)),
		report_every=int(payload.get("report_every",300)),
		change_by=float(payload.get("change_by",0.0)),
		enabled=bool(payload.get("enabled",True)),
		retain=bool(payload.get("retain",True)),
		device_class=payload.get("device_class",""),
		state_class=payload.get("state_class",""),
		icon=payload.get("icon",""),
		category=payload.get("category","diagnostic"),
		topic_suffix=payload.get("topic_suffix",payload["key"]),
		attributes=dict(payload.get("attributes",{})),
	)
