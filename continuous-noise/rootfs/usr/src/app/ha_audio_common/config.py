from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_options(path: str="/data/options.json") -> dict[str,Any]:
	with Path(path).open("r",encoding="utf-8") as handle:
		data=json.load(handle)
	if not isinstance(data,dict):
		raise ValueError("Konfiguracja dodatku musi być obiektem JSON")
	return data
