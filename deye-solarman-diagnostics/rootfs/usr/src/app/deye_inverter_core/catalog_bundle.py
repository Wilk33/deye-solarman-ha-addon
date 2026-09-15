"""Load versioned catalog data from the repository or the packaged bundle."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

CATALOG_SET="deye_sg04_sg05_3ph_lv"


def catalog_directory() -> Path:
	packaged=Path(__file__).with_name("data")
	if (packaged/"catalog-index.yaml").is_file():
		return packaged
	return Path(__file__).resolve().parents[2]/"catalogs/models"/CATALOG_SET


def load_map(map_id: str, transport_id: str, directory: Path | None=None) -> dict[str,Any]:
	root=(directory or catalog_directory()).resolve()
	index=yaml.safe_load((root/"catalog-index.yaml").read_text(encoding="utf-8"))
	if index.get("format") != 1 or index.get("catalog_set") != CATALOG_SET:
		raise ValueError("Invalid catalog index")
	metadata=index["maps"][map_id]
	if transport_id not in metadata["transports"]:
		raise ValueError(f"Map {map_id} does not support {transport_id}")
	path=(root/metadata["file"]).resolve()
	if path.parent != root:
		raise ValueError("Map file must stay inside catalog directory")
	data=path.read_bytes()
	if hashlib.sha256(data).hexdigest() != metadata["sha256"]:
		raise ValueError(f"Catalog checksum mismatch: {map_id}")
	result=yaml.safe_load(data)
	if result.get("format") != 1 or result.get("map_id") != map_id or result.get("catalog_set") != CATALOG_SET:
		raise ValueError("Invalid map identity")
	if result.get("transports") != metadata["transports"] or result.get("writable") != metadata["writable"]:
		raise ValueError("Map capability mismatch")
	return result


def legacy_telemetry_payload() -> dict[str,Any]:
	telemetry=load_map("telemetry","solarman_tcp")
	extra=load_map("telemetry_plus","solarman_tcp")
	return {"version":2,"sensors":telemetry["sensors"],"bms_pack":extra["bms_pack"]}
