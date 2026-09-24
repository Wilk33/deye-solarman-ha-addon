"""Load the writable control catalog selected in add-on configuration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request
from urllib.request import urlopen

import yaml

from .models import CatalogConfig


LOGGER=logging.getLogger(__name__)
_METHODS={"NumberRWSensor","SelectRWSensor","SwitchRWSensor","TimeRWSensor","SystemTimeRWSensor"}


@dataclass(frozen=True,slots=True)
class RemoteControlCatalog:
	commands: list[dict[str,Any]]
	source: str


def load_remote_control_catalog(config: CatalogConfig) -> RemoteControlCatalog:
	if not config.control_url:
		return RemoteControlCatalog([],"disabled")
	if config.refresh_on_start:
		try:
			payload=_download(config.control_url,config.timeout)
			_validate_payload(payload)
			_save_cache(config.control_cache_file,payload)
			return RemoteControlCatalog(payload["commands"],"github")
		except (OSError,ValueError,yaml.YAMLError) as error:
			LOGGER.warning("Remote control catalog refresh failed: %s",error)
	cached=_load_cache(config.control_cache_file)
	if cached is not None:
		return RemoteControlCatalog(cached["commands"],"cache")
	return RemoteControlCatalog([],"unavailable")


def _download(url: str, timeout: int) -> dict[str,Any]:
	request=Request(url,headers={"Accept":"application/yaml"})
	with urlopen(request,timeout=timeout) as response:
		payload=yaml.safe_load(response.read().decode("utf-8"))
	if not isinstance(payload,dict):
		raise ValueError("control catalog root must be an object")
	return payload


def _load_cache(path: str) -> dict[str,Any] | None:
	target=Path(path)
	if not target.exists():
		return None
	try:
		payload=yaml.safe_load(target.read_text(encoding="utf-8"))
		if not isinstance(payload,dict):
			raise ValueError("control catalog root must be an object")
		_validate_payload(payload)
		return payload
	except (OSError,ValueError,yaml.YAMLError) as error:
		LOGGER.warning("Cached control catalog is invalid: %s",error)
		return None


def _save_cache(path: str, payload: dict[str,Any]) -> None:
	target=Path(path)
	target.parent.mkdir(parents=True,exist_ok=True)
	temporary=target.with_name(f".{target.name}.tmp")
	temporary.write_text(yaml.safe_dump(payload,sort_keys=False,allow_unicode=True),encoding="utf-8")
	temporary.replace(target)


def _validate_payload(payload: dict[str,Any]) -> None:
	if payload.get("format") != 1 or payload.get("map_id") != "control" or payload.get("catalog_set") != "deye_sg04_sg05_3ph_lv":
		raise ValueError("Invalid control catalog identity")
	commands=payload.get("commands")
	if not isinstance(commands,list):
		raise ValueError("control catalog commands must be a list")
	keys=set()
	for index,entry in enumerate(commands):
		if not isinstance(entry,dict):
			raise ValueError(f"control catalog commands[{index}] must be an object")
		key=entry.get("key")
		if not isinstance(key,str) or not key or key in keys:
			raise ValueError(f"control catalog commands[{index}].key must be unique and non-empty")
		keys.add(key)
		if not isinstance(entry.get("name"),str) or not entry["name"]:
			raise ValueError(f"control catalog commands[{index}].name must be non-empty text")
		registers=entry.get("registers")
		if not isinstance(registers,list) or not registers or not all(type(register) is int and 0 <= register <= 65535 for register in registers):
			raise ValueError(f"control catalog commands[{index}].registers must contain Modbus addresses")
		if entry.get("method") not in _METHODS:
			raise ValueError(f"control catalog commands[{index}].method is unsupported")
		mode=entry.get("mode")
		if mode is not None and (entry["method"] != "NumberRWSensor" or mode not in {"box","slider"}):
			raise ValueError(f"control catalog commands[{index}].mode is unsupported")
		if not isinstance(entry.get("factor"),(int,float)) or not isinstance(entry.get("unit"),str) or type(entry.get("bitmask")) is not int:
			raise ValueError(f"control catalog commands[{index}] has invalid decoding")
