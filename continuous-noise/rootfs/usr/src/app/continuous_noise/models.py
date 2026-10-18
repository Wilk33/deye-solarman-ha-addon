from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SUPPORTED_NOISES={"white","pink","brown","violet"}


@dataclass(frozen=True)
class NoiseDefinition:
	key: str
	name: str
	noise_type: str

	@classmethod
	def from_dict(cls,data: dict[str,Any]) -> "NoiseDefinition":
		key=str(data.get("key","")).strip().lower().replace(" ","_")
		name=str(data.get("name") or key).strip()
		noise_type=str(data.get("type","")).strip().lower()
		if not key or not all(character.isalnum() or character == "_" for character in key):
			raise ValueError(f"Nieprawidłowy klucz szumu: {key}")
		if noise_type not in SUPPORTED_NOISES:
			raise ValueError(f"Nieobsługiwany rodzaj szumu: {noise_type}")
		return cls(key,name,noise_type)


class NoiseSelection:
	def __init__(self,definitions: list[NoiseDefinition]) -> None:
		keys=[definition.key for definition in definitions]
		if len(keys) != len(set(keys)):
			raise ValueError("Klucze szumów nie mogą się powtarzać")
		self.definitions={definition.key:definition for definition in definitions}
		self.requested: str | None=None
		self.alarm_active=False

	@property
	def playing(self) -> str | None:
		return None if self.alarm_active else self.requested

	def command(self,key: str,payload: str) -> None:
		if key not in self.definitions:
			raise ValueError(f"Nieznany szum: {key}")
		value=str(payload).upper()
		if value == "ON":
			self.requested=key
		elif value == "OFF":
			if self.requested == key:
				self.requested=None
		else:
			raise ValueError(f"Nieprawidłowa komenda szumu: {payload}")

	def set_alarm_active(self,active: bool) -> None:
		self.alarm_active=bool(active)

	def states(self) -> dict[str,str]:
		return {key:"ON" if key == self.requested else "OFF" for key in self.definitions}
