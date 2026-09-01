from __future__ import annotations

import logging
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request
from urllib.request import urlopen

import yaml

from .models import CatalogConfig
from .models import SensorDefinition


LOGGER=logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RemoteCatalog:
	sensors: list[dict[str, Any]]
	source: str


def load_remote_catalog(config: CatalogConfig, force_refresh: bool=False) -> RemoteCatalog:
	if config.refresh_on_start or force_refresh:
		try:
			payload=_download(config.url,config.timeout)
			_validate_payload(payload)
			_save_cache(config.cache_file,payload)
			LOGGER.info("Remote register catalog loaded source=github entries=%s",len(payload["sensors"]))
			return RemoteCatalog(payload["sensors"],"github")
		except (OSError,ValueError,yaml.YAMLError) as error:
			LOGGER.warning("Remote register catalog refresh failed: %s",error)

	cached=_load_cache(config.cache_file)
	if cached is not None:
		LOGGER.info("Remote register catalog loaded source=cache entries=%s",len(cached["sensors"]))
		return RemoteCatalog(cached["sensors"],"cache")
	LOGGER.info("Remote register catalog unavailable; using built-in catalog")
	return RemoteCatalog([],"built-in")


def apply_remote_catalog(sensors: list[SensorDefinition], catalog: RemoteCatalog) -> list[SensorDefinition]:
	merged={sensor.key: sensor for sensor in sensors}
	for entry in catalog.sensors:
		key=entry["key"]
		if entry.get("remove",False):
			merged.pop(key,None)
			continue
		definition=dict(entry.get("definition",entry))
		definition.setdefault("key",key)
		current=merged.get(key)
		merged[key]=_merge_definition(current,definition)
	return list(merged.values())


def _download(url: str, timeout: int) -> dict[str, Any]:
	request=Request(url,headers={"Accept": "application/yaml"})
	with urlopen(request,timeout=timeout) as response:
		payload=yaml.safe_load(response.read().decode("utf-8"))
	if not isinstance(payload,dict):
		raise ValueError("catalog root must be an object")
	return payload


def _load_cache(path: str) -> dict[str, Any] | None:
	target=Path(path)
	if not target.exists():
		return None
	try:
		payload=yaml.safe_load(target.read_text(encoding="utf-8"))
		if not isinstance(payload,dict):
			raise ValueError("catalog root must be an object")
		_validate_payload(payload)
		return payload
	except (OSError,ValueError,yaml.YAMLError) as error:
		LOGGER.warning("Cached register catalog is invalid: %s",error)
		return None


def _save_cache(path: str, payload: dict[str, Any]) -> None:
	target=Path(path)
	target.parent.mkdir(parents=True,exist_ok=True)
	temporary=target.with_name(f".{target.name}.tmp")
	temporary.write_text(yaml.safe_dump(payload,sort_keys=False,allow_unicode=True),encoding="utf-8")
	temporary.replace(target)


def _validate_payload(payload: dict[str, Any]) -> None:
	if payload.get("version") != 1:
		raise ValueError("catalog version must be 1")
	sensors=payload.get("sensors")
	if not isinstance(sensors,list):
		raise ValueError("catalog sensors must be a list")
	for index, entry in enumerate(sensors):
		if not isinstance(entry,dict) or not isinstance(entry.get("key"),str) or not entry["key"]:
			raise ValueError(f"catalog sensors[{index}].key must be a non-empty string")
		if entry.get("remove",False):
			continue
		definition=entry.get("definition",entry)
		if not isinstance(definition,dict):
			raise ValueError(f"catalog sensors[{index}].definition must be an object")
		if "registers" in definition and (
			not isinstance(definition["registers"],list)
			or not all(type(register) is int and 0 <= register <= 65535 for register in definition["registers"])
		):
			raise ValueError(f"catalog sensors[{index}].registers must contain Modbus addresses")


def _merge_definition(current: SensorDefinition | None, payload: dict[str, Any]) -> SensorDefinition:
	data=asdict(current) if current else {}
	for key,value in payload.items():
		if key == "type":
			data["register_type"]=value
		elif key in SensorDefinition.__dataclass_fields__:
			data[key]=value
	if not current:
		data.setdefault("key",payload.get("key"))
		data.setdefault("name",data.get("key",""))
		data.setdefault("register_type",payload.get("type","uint16"))
		data.setdefault("registers",[])
	if not isinstance(data.get("key"),str) or not data["key"]:
		raise ValueError("catalog sensor key must be a non-empty string")
	if not isinstance(data.get("name"),str) or not data["name"]:
		raise ValueError(f"catalog sensor {data['key']}: name must be a non-empty string")
	return SensorDefinition(**data)
