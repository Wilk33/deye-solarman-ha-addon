"""Per-transport runtime scheduling without application lifecycle ownership."""
from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any

from .models import SensorDefinition
from .scheduler import MonotonicClock
from .scheduler import PerEntityScheduler
from .transport import RegisterTransport
from .transport_manager import TransportManager
from .transport_manager import TransportSlot


ReadCallback=Callable[[RegisterTransport,tuple[SensorDefinition,...]],Any]


class TransportWorker:
	"""Run due sensors through exactly one transport manager slot."""

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
		due=tuple(
			sensor
			for sensor in self._scheduler.due(started_at)
			if sensor.enabled and sensor.transport == self.transport_id
		)
		if not due:
			return None

		attempted_keys: tuple[str,...]=()
		def operation(client: RegisterTransport) -> Any:
			nonlocal attempted_keys
			attempted_keys=tuple(sensor.key for sensor in due)
			return self._read_callback(client,due)

		try:
			return self._manager.run(self.transport_id,operation)
		finally:
			if attempted_keys:
				completed_at=max(started_at,self._clock())
				for key in attempted_keys:
					try:
						self._scheduler.mark_read(key,completed_at)
					except KeyError:
						pass

	def wait_time(self, now: float | None=None) -> float | None:
		current=self._clock() if now is None else now
		scheduled_wait=self._scheduler.wait_time(current)
		if scheduled_wait is None:
			return None
		if self._slot.online or self._slot.next_reconnect_at <= current:
			return scheduled_wait
		return max(scheduled_wait,self._slot.next_reconnect_at-current)
