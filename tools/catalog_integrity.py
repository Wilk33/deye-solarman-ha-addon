"""Shared catalog discovery, integrity and structural validation."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from packages.deye_inverter_core.formula import FormulaError
from packages.deye_inverter_core.formula import validate_formula

ALLOWED_MAPS={"telemetry":"sensors","control":"commands"}


class CatalogValidationError(ValueError):
	"""Raised when a model catalog cannot be trusted or represented."""


@dataclass(frozen=True)
class CatalogMap:
	map_id: str
	path: Path
	metadata: dict[str,Any]
	payload: dict[str,Any]
	definition_key: str
	definitions: tuple[dict[str,Any],...]


@dataclass(frozen=True)
class CatalogModel:
	path: Path
	catalog_set: str
	index: dict[str,Any]
	maps: dict[str,CatalogMap]


def normalized_text_bytes(path: Path) -> bytes:
	return path.read_text(encoding="utf-8").replace("\r\n","\n").replace("\r","\n").encode("utf-8")


def normalized_sha256(path: Path) -> str:
	return hashlib.sha256(normalized_text_bytes(path)).hexdigest()


def _context(model_dir: Path,map_id: str | None=None,file_name: str | None=None) -> str:
	parts=[f"model={model_dir.name}"]
	if map_id is not None:
		parts.append(f"map={map_id}")
	if file_name is not None:
		parts.append(f"file={file_name}")
	return " ".join(parts)


def _fail(model_dir: Path,condition: str,map_id: str | None=None,file_name: str | None=None) -> None:
	raise CatalogValidationError(f"{_context(model_dir,map_id,file_name)}: {condition}")


def _load_mapping(path: Path,model_dir: Path,map_id: str | None=None) -> dict[str,Any]:
	try:
		payload=yaml.safe_load(normalized_text_bytes(path))
	except (OSError,UnicodeError,yaml.YAMLError) as error:
		_fail(model_dir,f"invalid YAML or JSON: {error}",map_id,path.name)
	if not isinstance(payload,dict):
		_fail(model_dir,"document must be an object",map_id,path.name)
	return payload


def _validate_transports(value: Any,model_dir: Path,map_id: str,file_name: str) -> list[str]:
	if not isinstance(value,list) or not value:
		_fail(model_dir,"transports must be a non-empty list",map_id,file_name)
	if any(not isinstance(item,str) or not item for item in value):
		_fail(model_dir,"each transport must be a non-empty string",map_id,file_name)
	if len(value) != len(set(value)):
		_fail(model_dir,"transports must be unique",map_id,file_name)
	return value


def _validate_definitions(
	value: Any,
	model_dir: Path,
	map_id: str,
	file_name: str,
) -> tuple[dict[str,Any],...]:
	if not isinstance(value,list):
		_fail(model_dir,f"{ALLOWED_MAPS[map_id]} must be a list",map_id,file_name)
	definitions=[]
	keys=set()
	for position,definition in enumerate(value):
		if not isinstance(definition,dict):
			_fail(model_dir,f"definition {position} must be an object",map_id,file_name)
		key=definition.get("key")
		if not isinstance(key,str) or not key:
			_fail(model_dir,f"definition {position} key must be a non-empty string",map_id,file_name)
		if key in keys:
			_fail(model_dir,f"duplicate key {key}",map_id,file_name)
		keys.add(key)
		registers=definition.get("registers")
		formula=definition.get("formula","")
		if not isinstance(formula,str):
			_fail(model_dir,f"definition {key} formula must be text",map_id,file_name)
		if formula:
			if map_id != "telemetry" or definition.get("type") != "auto":
				_fail(model_dir,f"definition {key} formula requires telemetry type auto",map_id,file_name)
			if registers != []:
				_fail(model_dir,f"definition {key} formula cannot declare direct registers",map_id,file_name)
			try:
				validate_formula(formula)
			except FormulaError as error:
				_fail(model_dir,f"definition {key} has invalid formula: {error}",map_id,file_name)
		elif definition.get("type") == "auto":
			_fail(model_dir,f"definition {key} type auto requires a formula",map_id,file_name)
		elif not isinstance(registers,list) or not registers:
			_fail(model_dir,f"definition {key} registers must be a non-empty list",map_id,file_name)
		if any(not isinstance(register,int) or isinstance(register,bool) for register in registers):
			_fail(model_dir,f"definition {key} registers must contain integers",map_id,file_name)
		definitions.append(definition)
	return tuple(definitions)


def _load_catalog_map(model_dir: Path,catalog_set: str,map_id: str,metadata: Any) -> CatalogMap:
	if map_id not in ALLOWED_MAPS:
		_fail(model_dir,f"unsupported map id {map_id}",map_id)
	if not isinstance(metadata,dict):
		_fail(model_dir,"map metadata must be an object",map_id)
	file_name=metadata.get("file")
	if not isinstance(file_name,str) or not file_name:
		_fail(model_dir,"map file must be a non-empty string",map_id)
	model_root=model_dir.resolve()
	map_path=(model_dir/file_name).resolve()
	if not map_path.is_relative_to(model_root):
		_fail(model_dir,"map path is outside model directory",map_id,file_name)
	if not map_path.is_file():
		_fail(model_dir,"declared map file does not exist",map_id,file_name)
	expected_checksum=metadata.get("sha256")
	if not isinstance(expected_checksum,str) or len(expected_checksum) != 64:
		_fail(model_dir,"sha256 must contain 64 hexadecimal characters",map_id,file_name)
	try:
		int(expected_checksum,16)
	except ValueError:
		_fail(model_dir,"sha256 must contain 64 hexadecimal characters",map_id,file_name)
	if normalized_sha256(map_path) != expected_checksum.lower():
		_fail(model_dir,"checksum mismatch",map_id,file_name)
	payload=_load_mapping(map_path,model_dir,map_id)
	checks={
		"format":1,
		"map_id":map_id,
		"catalog_set":catalog_set,
		"purpose":map_id,
	}
	for field,expected in checks.items():
		if payload.get(field) != expected:
			_fail(model_dir,f"{field} must equal {expected!r}",map_id,file_name)
	writable=metadata.get("writable")
	if not isinstance(writable,bool):
		_fail(model_dir,"index writable must be boolean",map_id,file_name)
	if payload.get("writable") is not writable:
		_fail(model_dir,"writable does not match index",map_id,file_name)
	index_transports=_validate_transports(metadata.get("transports"),model_dir,map_id,file_name)
	payload_transports=_validate_transports(payload.get("transports"),model_dir,map_id,file_name)
	if payload_transports != index_transports:
		_fail(model_dir,"transports do not match index",map_id,file_name)
	definition_key=ALLOWED_MAPS[map_id]
	definitions=_validate_definitions(payload.get(definition_key),model_dir,map_id,file_name)
	return CatalogMap(
		map_id=map_id,
		path=map_path,
		metadata=dict(metadata),
		payload=payload,
		definition_key=definition_key,
		definitions=definitions,
	)


def load_catalog_model(model_dir: Path) -> CatalogModel:
	model_dir=model_dir.resolve()
	index_path=model_dir/"catalog-index.yaml"
	if not index_path.is_file():
		_fail(model_dir,"catalog-index.yaml does not exist")
	index=_load_mapping(index_path,model_dir)
	if index.get("format") != 1:
		_fail(model_dir,"index format must equal 1")
	catalog_set=index.get("catalog_set")
	if catalog_set != model_dir.name:
		_fail(model_dir,f"catalog_set must equal directory name {model_dir.name!r}")
	maps_payload=index.get("maps")
	if not isinstance(maps_payload,dict) or not maps_payload:
		_fail(model_dir,"maps must be a non-empty object")
	maps={
		map_id:_load_catalog_map(model_dir,catalog_set,map_id,metadata)
		for map_id,metadata in maps_payload.items()
	}
	return CatalogModel(path=model_dir,catalog_set=catalog_set,index=index,maps=maps)


def discover_catalog_models(models_root: Path) -> tuple[CatalogModel,...]:
	return tuple(
		load_catalog_model(path)
		for path in sorted(models_root.iterdir(),key=lambda item:item.name)
		if path.is_dir() and (path/"catalog-index.yaml").is_file()
	)
