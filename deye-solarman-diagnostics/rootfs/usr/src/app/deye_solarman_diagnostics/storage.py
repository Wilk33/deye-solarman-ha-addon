from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import SensorState


LOGGER=logging.getLogger(__name__)


def load_state(path: str) -> dict[str, SensorState]:
	target=Path(path)
	if not target.exists():
		return {}
	try:
		with target.open("r", encoding="utf-8") as handle:
			payload=json.load(handle)
	except (OSError, json.JSONDecodeError) as error:
		LOGGER.warning("Ignoring unreadable state file %s: %s", target, error)
		return {}
	if not isinstance(payload, dict):
		LOGGER.warning("Ignoring invalid state file %s: root value must be an object", target)
		return {}

	state: dict[str, SensorState]={}
	for key, value in payload.items():
		if not isinstance(key, str) or not isinstance(value, dict):
			LOGGER.warning("Ignoring invalid state entry in %s", target)
			continue
		try:
			state[key]=SensorState(**value)
		except TypeError as error:
			LOGGER.warning("Ignoring invalid state entry %s: %s", key, error)
	return state


def save_state(path: str, state: dict[str, SensorState]) -> None:
	target=Path(path)
	target.parent.mkdir(parents=True, exist_ok=True)
	_write_json(target, {key: asdict(value) for key, value in state.items()})


def save_scan_report(path: str, report: list[dict[str, Any]]) -> None:
	target=Path(path)
	target.parent.mkdir(parents=True, exist_ok=True)
	_write_json(target, report)


def _write_json(target: Path, payload: Any) -> None:
	temporary=target.with_name(f".{target.name}.tmp")
	with temporary.open("w", encoding="utf-8") as handle:
		json.dump(payload, handle, indent=2, sort_keys=True)
	temporary.replace(target)
