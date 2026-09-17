from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterable
import threading
import time

from .models import PollingConfig
from .models import SensorDefinition


MonotonicClock=Callable[[],float]
_MODEL_DEFAULT_READ_EVERY=SensorDefinition.__dataclass_fields__["read_every"].default


class PerEntityScheduler:
	"""Track independent monotonic deadlines for one transport's sensors."""

	def __init__(
		self,
		sensors: Iterable[SensorDefinition],
		polling: PollingConfig,
		*,
		clock: MonotonicClock=time.monotonic,
		coalescing_window: float | None=None,
	) -> None:
		self._polling=polling
		self._clock=clock
		self._coalescing_window=(
			polling.read_message_spacing
			if coalescing_window is None
			else coalescing_window
		)
		if self._coalescing_window < 0:
			raise ValueError("Coalescing window cannot be negative")
		self._lock=threading.RLock()
		self._sensors: dict[str,SensorDefinition]={}
		self._next_due: dict[str,float]={}
		self.sync(sensors,now=self._clock())

	@property
	def next_due(self) -> float | None:
		with self._lock:
			return min(self._next_due.values(),default=None)

	def due(self, now: float | None=None) -> tuple[SensorDefinition,...]:
		current=self._clock() if now is None else now
		cutoff=current+self._coalescing_window
		with self._lock:
			keys=sorted(
				(key for key,deadline in self._next_due.items() if deadline <= cutoff),
				key=lambda key:(self._next_due[key],key),
			)
			return tuple(self._sensors[key] for key in keys)

	def mark_read(self, key: str, now: float | None=None) -> None:
		current=self._clock() if now is None else now
		with self._lock:
			sensor=self._sensors[key]
			self._next_due[key]=current+self._effective_interval(sensor)

	def sync(self, sensors: Iterable[SensorDefinition], *, now: float | None=None) -> None:
		current=self._clock() if now is None else now
		active: dict[str,SensorDefinition]={}
		for sensor in sensors:
			if not sensor.enabled:
				continue
			if sensor.key in active:
				raise ValueError(f"Duplicate sensor key: {sensor.key}")
			active[sensor.key]=sensor
		with self._lock:
			preserved={key:self._next_due[key] for key in active if key in self._next_due}
			self._sensors=active
			self._next_due={key:preserved.get(key,current) for key in active}

	def wait_time(self, now: float | None=None) -> float | None:
		current=self._clock() if now is None else now
		deadline=self.next_due
		if deadline is None:
			return None
		return max(0.0,deadline-current)

	def _effective_interval(self, sensor: SensorDefinition) -> float:
		if sensor.schedule == "slow":
			if sensor.read_every > 0 and sensor.read_every != _MODEL_DEFAULT_READ_EVERY:
				return float(sensor.read_every)
			return float(self._polling.slow_interval)
		if sensor.read_every > 0:
			return float(sensor.read_every)
		return float(self._polling.default_interval)


def group_sensors_for_read(sensors: list[SensorDefinition], config: PollingConfig) -> list[list[SensorDefinition]]:
	enabled=[sensor for sensor in sensors if sensor.enabled]
	sorted_sensors=sorted(enabled, key=lambda item: min(item.registers))
	groups: list[list[SensorDefinition]]=[]

	for sensor in sorted_sensors:
		if not groups:
			groups.append([sensor])
			continue
		group=groups[-1]
		group_start=min(register for member in group for register in member.registers)
		current_end=max(register for member in group for register in member.registers)
		next_start=min(sensor.registers)
		next_end=max(sensor.registers)
		new_count=max(current_end, next_end)-group_start+1
		if next_start-current_end <= config.batch_gap and new_count <= config.max_registers_per_request:
			group.append(sensor)
		else:
			groups.append([sensor])

	return groups
