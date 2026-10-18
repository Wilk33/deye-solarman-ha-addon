from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class AlarmLevel(str,Enum):
	DISABLED="disabled"
	UNAVAILABLE="unavailable"
	OK="ok"
	WARNING_LOW="warning_low"
	WARNING_HIGH="warning_high"
	ALARM_LOW="alarm_low"
	ALARM_HIGH="alarm_high"

	@property
	def severity(self) -> int:
		return {
			AlarmLevel.DISABLED:-1,
			AlarmLevel.UNAVAILABLE:1,
			AlarmLevel.OK:0,
			AlarmLevel.WARNING_LOW:2,
			AlarmLevel.WARNING_HIGH:2,
			AlarmLevel.ALARM_LOW:3,
			AlarmLevel.ALARM_HIGH:3,
		}[self]

	@property
	def state(self) -> str:
		if self in {AlarmLevel.ALARM_LOW,AlarmLevel.ALARM_HIGH}:
			return "alarm"
		if self in {AlarmLevel.WARNING_LOW,AlarmLevel.WARNING_HIGH}:
			return "warning"
		return self.value


def optional_number(value: Any) -> float | None:
	if value is None or str(value).strip() == "":
		return None
	try:
		return float(str(value).replace(",","."))
	except ValueError as error:
		raise ValueError(f"Nieprawidłowa wartość progu: {value}") from error


@dataclass(frozen=True)
class MonitorDefinition:
	entity_id: str
	name: str
	alarm_low: float | None=None
	warning_low: float | None=None
	warning_high: float | None=None
	alarm_high: float | None=None

	@classmethod
	def from_dict(cls,data: dict[str,Any]) -> "MonitorDefinition":
		entity_id=str(data.get("entity_id","")).strip()
		if not entity_id or "." not in entity_id:
			raise ValueError(f"Nieprawidłowy entity_id: {entity_id}")
		monitor=cls(
			entity_id=entity_id,
			name=str(data.get("name") or entity_id).strip(),
			alarm_low=optional_number(data.get("alarm_low")),
			warning_low=optional_number(data.get("warning_low")),
			warning_high=optional_number(data.get("warning_high")),
			alarm_high=optional_number(data.get("alarm_high")),
		)
		monitor.validate()
		return monitor

	@property
	def enabled(self) -> bool:
		return any(value is not None for value in (
			self.alarm_low,self.warning_low,self.warning_high,self.alarm_high,
		))

	def validate(self) -> None:
		if self.alarm_low is not None and self.warning_low is not None and self.alarm_low > self.warning_low:
			raise ValueError(f"alarm_low musi być mniejszy lub równy warning_low dla {self.entity_id}")
		if self.warning_high is not None and self.alarm_high is not None and self.warning_high > self.alarm_high:
			raise ValueError(f"warning_high musi być mniejszy lub równy alarm_high dla {self.entity_id}")
		low=max(value for value in (self.alarm_low,self.warning_low) if value is not None) if any(value is not None for value in (self.alarm_low,self.warning_low)) else None
		high=min(value for value in (self.warning_high,self.alarm_high) if value is not None) if any(value is not None for value in (self.warning_high,self.alarm_high)) else None
		if low is not None and high is not None and low >= high:
			raise ValueError(f"Progi dolne muszą być mniejsze od progów górnych dla {self.entity_id}")

	def evaluate(self,value: float) -> AlarmLevel:
		if not self.enabled:
			return AlarmLevel.DISABLED
		if self.alarm_low is not None and value <= self.alarm_low:
			return AlarmLevel.ALARM_LOW
		if self.alarm_high is not None and value >= self.alarm_high:
			return AlarmLevel.ALARM_HIGH
		if self.warning_low is not None and value <= self.warning_low:
			return AlarmLevel.WARNING_LOW
		if self.warning_high is not None and value >= self.warning_high:
			return AlarmLevel.WARNING_HIGH
		return AlarmLevel.OK

	def threshold_for(self,level: AlarmLevel) -> float | None:
		return {
			AlarmLevel.ALARM_LOW:self.alarm_low,
			AlarmLevel.WARNING_LOW:self.warning_low,
			AlarmLevel.WARNING_HIGH:self.warning_high,
			AlarmLevel.ALARM_HIGH:self.alarm_high,
		}.get(level)


def aggregate_level(levels: list[AlarmLevel]) -> AlarmLevel:
	if not levels:
		return AlarmLevel.DISABLED
	return max(levels,key=lambda level:level.severity)
