"""Per-transport runtime scheduling without application lifecycle ownership."""
from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterable
import time
from typing import Any

from .models import SensorDefinition
from .scheduler import MonotonicClock
from .scheduler import PerEntityScheduler
from .transport import RegisterTransport
from .transport_manager import TransportManager
from .transport_manager import TransportSlot


AttemptRecorder=Callable[[Iterable[str]],None]
ReadCallback=Callable[[RegisterTransport,tuple[SensorDefinition,...],AttemptRecorder],Any]


class TransportWorker:
	"""Run due sensors through exactly one transport manager slot.

	The read callback must report keys through its attempt recorder immediately
	before starting each physical read group.
	"""

	def __init__(
		self,
		manager: TransportManager,
		slot: TransportSlot,
		scheduler: PerEntityScheduler,
		read_callback: ReadCallback,
		*,
		clock: MonotonicClock=time.monotonic,
	) -> None:
		self._manager=manager
		self._slot=slot
		self._scheduler=scheduler
		self._read_callback=read_callback
		self._clock=clock

	@property
	def transport_id(self) -> str:
		return self._slot.transport_id

	def run_due(self, now: float | None=None) -> Any | None:
		started_at=self._clock() if now is None else now
		due=self._scheduler.due(started_at,predicate=self._uses_worker_transport)
		if not due:
			return None

		due_keys={sensor.key for sensor in due}
		attempted_keys: set[str]=set()
		def mark_attempted(keys: Iterable[str]) -> None:
			reported=tuple(keys)
			unknown=sorted(set(reported)-due_keys)
			if unknown:
				raise ValueError(f"Attempted keys are not due for {self.transport_id}: {unknown}")
			attempted_keys.update(reported)

		def operation(client: RegisterTransport) -> Any:
			return self._read_callback(client,due,mark_attempted)

		try:
			return self._manager.run(self.transport_id,operation)
		finally:
			if attempted_keys:
				completed_at=max(started_at,self._clock())
				for key in (sensor.key for sensor in due if sensor.key in attempted_keys):
					try:
						self._scheduler.mark_read(key,completed_at)
					except KeyError:
						pass

	def wait_time(self, now: float | None=None) -> float | None:
		current=self._clock() if now is None else now
		scheduled_wait=self._scheduler.wait_time(current,predicate=self._uses_worker_transport)
		if scheduled_wait is None:
			return None
		if self._slot.online or self._slot.next_reconnect_at <= current:
			return scheduled_wait
		return max(scheduled_wait,self._slot.next_reconnect_at-current)

	def _uses_worker_transport(self, sensor: SensorDefinition) -> bool:
		return sensor.enabled and sensor.transport == self.transport_id
