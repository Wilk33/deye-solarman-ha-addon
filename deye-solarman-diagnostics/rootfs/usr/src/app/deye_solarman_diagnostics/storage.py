from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import SensorState


def load_state(path: str) -> dict[str, SensorState]:
	target=Path(path)
	if not target.exists():
		return {}
	with target.open("r", encoding="utf-8") as handle:
		payload=json.load(handle)
	return {
		key: SensorState(**value)
		for key, value in payload.items()
	}


def save_state(path: str, state: dict[str, SensorState]) -> None:
	target=Path(path)
	target.parent.mkdir(parents=True, exist_ok=True)
	payload={key: asdict(value) for key, value in state.items()}
	with target.open("w", encoding="utf-8") as handle:
		json.dump(payload, handle, indent=2, sort_keys=True)


def save_scan_report(path: str, report: list[dict[str, Any]]) -> None:
	target=Path(path)
	target.parent.mkdir(parents=True, exist_ok=True)
	with target.open("w", encoding="utf-8") as handle:
		json.dump(report, handle, indent=2, sort_keys=True)
