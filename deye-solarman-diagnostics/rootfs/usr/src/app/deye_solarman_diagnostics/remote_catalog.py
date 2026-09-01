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
from .logging_utils import success


LOGGER=logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RemoteCatalog:
	sensors: list[dict[str, Any]]
	source: str
	bms_pack: dict[str, Any] | None=None
	version: int=1

	@property
	def definition_count(self) -> int:
		if not self.bms_pack:
			return len(self.sensors)
		templates=self.bms_pack.get("sensors",[])
		return len(self.sensors)+len(templates) if isinstance(templates,list) else len(self.sensors)


def load_remote_catalog(config: CatalogConfig, force_refresh: bool=False) -> RemoteCatalog:
	if config.refresh_on_start or force_refresh:
		try:
			payload=_download(config.url,config.timeout)
			_validate_payload(payload)
			_save_cache(config.cache_file,payload)
			catalog=_catalog_from_payload(payload,"github")
			success(LOGGER,"Remote register catalog loaded source=github entries=%s",catalog.definition_count)
			return catalog
		except (OSError,ValueError,yaml.YAMLError) as error:
			LOGGER.warning("Remote register catalog refresh failed: %s",error)

	cached=_load_cache(config.cache_file)
	if cached is not None:
		catalog=_catalog_from_payload(cached,"cache")
		success(LOGGER,"Remote register catalog loaded source=cache entries=%s",catalog.definition_count)
		return catalog
	LOGGER.info("Remote register catalog unavailable; using built-in catalog")
	return RemoteCatalog([],"built-in")


def apply_remote_catalog(
	sensors: list[SensorDefinition],
	catalog: RemoteCatalog,
	bms_pack_count: int=0,
) -> list[SensorDefinition]:
	merged={} if catalog.version >= 2 else {sensor.key: sensor for sensor in sensors}
	for entry in catalog.sensors:
		key=entry["key"]
		if entry.get("remove",False):
			merged.pop(key,None)
			continue
		definition=dict(entry.get("definition",entry))
		definition.setdefault("key",key)
		current=merged.get(key)
		merged[key]=_merge_definition(current,definition)
	if catalog.bms_pack and bms_pack_count:
		_apply_bms_pack_template(merged,catalog.bms_pack,bms_pack_count)
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


def _catalog_from_payload(payload: dict[str, Any], source: str) -> RemoteCatalog:
	bms_pack=payload.get("bms_pack")
	return RemoteCatalog(
		payload["sensors"],
		source,
		bms_pack if isinstance(bms_pack,dict) else None,
		int(payload["version"]),
	)


def _save_cache(path: str, payload: dict[str, Any]) -> None:
	target=Path(path)
	target.parent.mkdir(parents=True,exist_ok=True)
	temporary=target.with_name(f".{target.name}.tmp")
	temporary.write_text(yaml.safe_dump(payload,sort_keys=False,allow_unicode=True),encoding="utf-8")
	temporary.replace(target)


def _validate_payload(payload: dict[str, Any]) -> None:
	if payload.get("version") not in {1,2}:
		raise ValueError("catalog version must be 1 or 2")
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
		_validate_definition_decoding(definition,f"catalog sensors[{index}]")
	if payload.get("version") == 2:
		_validate_bms_pack_template(payload.get("bms_pack"))


def _validate_bms_pack_template(template: Any) -> None:
	if not isinstance(template,dict):
		raise ValueError("catalog bms_pack must be an object for version 2")
	base=template.get("base_register")
	stride=template.get("register_stride")
	entries=template.get("sensors")
	if type(base) is not int or not 0 <= base <= 65535:
		raise ValueError("catalog bms_pack.base_register must be a Modbus address")
	if type(stride) is not int or stride <= 0:
		raise ValueError("catalog bms_pack.register_stride must be a positive integer")
	if not isinstance(entries,list) or not entries:
		raise ValueError("catalog bms_pack.sensors must be a non-empty list")
	for index,entry in enumerate(entries):
		if not isinstance(entry,dict):
			raise ValueError(f"catalog bms_pack.sensors[{index}] must be an object")
		for field in ("key","name"):
			value=entry.get(field)
			if not isinstance(value,str) or "{pack}" not in value:
				raise ValueError(f"catalog bms_pack.sensors[{index}].{field} must contain {{pack}}")
		offsets=entry.get("register_offsets")
		if not isinstance(offsets,list) or not offsets or not all(type(offset) is int and offset >= 0 for offset in offsets):
			raise ValueError(f"catalog bms_pack.sensors[{index}].register_offsets must be non-negative integers")
		if base+9*stride+max(offsets) > 65535:
			raise ValueError(f"catalog bms_pack.sensors[{index}] exceeds the supported ten-pack Modbus range")
		_validate_definition_decoding(entry,f"catalog bms_pack.sensors[{index}]")


def _validate_definition_decoding(definition: dict[str, Any], location: str) -> None:
	register_type=definition.get("type","uint16")
	if register_type not in {"uint16","int16","uint32","int32","hex","ascii"}:
		raise ValueError(f"{location}.type is unsupported")
	for field in ("word_order","byte_order"):
		value=definition.get(field,"high_low")
		if value not in {"high_low","low_high"}:
			raise ValueError(f"{location}.{field} must be high_low or low_high")


def _apply_bms_pack_template(
	merged: dict[str, SensorDefinition],
	template: dict[str, Any],
	pack_count: int,
) -> None:
	base=template["base_register"]
	stride=template["register_stride"]
	for pack in range(1,pack_count+1):
		for entry in template["sensors"]:
			definition=dict(entry)
			offsets=definition.pop("register_offsets")
			definition["registers"]=[base+(pack-1)*stride+offset for offset in offsets]
			for field in ("key","name","topic_suffix"):
				value=definition.get(field)
				if isinstance(value,str):
					definition[field]=_format_pack_template(value,pack)
			key=definition["key"]
			merged[key]=_merge_definition(merged.get(key),definition)


def _format_pack_template(value: str, pack: int) -> str:
	try:
		return value.format(pack=pack)
	except (IndexError,KeyError,ValueError) as error:
		raise ValueError(f"catalog BMS template has invalid placeholder: {value!r}") from error


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
