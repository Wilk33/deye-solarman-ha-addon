"""Independent connection state and locking for active register transports."""
from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import field
import threading
import time
from typing import Any
from typing import TypeVar

from .models import TransportPollingConfig
from .transport import RegisterTransport
from .transport import TransportConnectionClosedError


ResultT=TypeVar("ResultT")
MonotonicClock=Callable[[],float]


class _ReconnectPendingError(TransportConnectionClosedError):
	"""A slot is inside its reconnect cooldown."""


@dataclass(slots=True)
class TransportStatus:
	online: bool=False
	last_error: str | None=None
	error_count: int=0
	latency_ms: float=0.0
	next_reconnect_at: float=0.0


@dataclass(slots=True)
class TransportSlot:
	client: RegisterTransport
	polling: TransportPollingConfig
	reconnect_delay: float
	lock: Any=field(default_factory=threading.RLock,repr=False)
	status: TransportStatus=field(default_factory=TransportStatus)
	_has_connected: bool=field(default=False,init=False,repr=False)

	@property
	def transport(self) -> RegisterTransport:
		return self.client

	@property
	def transport_id(self) -> str:
		return self.client.transport_id

	@property
	def online(self) -> bool:
		return self.status.online

	@property
	def last_error(self) -> str | None:
		return self.status.last_error

	@property
	def error_count(self) -> int:
		return self.status.error_count

	@property
	def latency_ms(self) -> float:
		return self.status.latency_ms

	@property
	def next_reconnect_at(self) -> float:
		return self.status.next_reconnect_at


class TransportManager:
	def __init__(
		self,
		slots: Iterable[TransportSlot],
		*,
		clock: MonotonicClock=time.monotonic,
	) -> None:
		self._slots=tuple(slots)
		self._clock=clock
		self._by_id: dict[str,TransportSlot]={}
		for slot in self._slots:
			if slot.transport_id in self._by_id:
				raise ValueError(f"Duplicate transport id: {slot.transport_id}")
			self._by_id[slot.transport_id]=slot

	def get(self, transport_id: str) -> TransportSlot:
		try:
			return self._by_id[transport_id]
		except KeyError:
			raise KeyError(f"Unknown transport: {transport_id}") from None

	def available(self) -> tuple[TransportSlot,...]:
		return self._slots

	def run(
		self,
		transport_id: str,
		operation: Callable[[RegisterTransport],ResultT],
		*,
		before_io: Callable[[],None] | None=None,
	) -> ResultT:
		slot=self.get(transport_id)
		with slot.lock:
			if before_io is not None:
				before_io()
			try:
				self._ensure_connected(slot)
			except _ReconnectPendingError:
				raise
			except TransportConnectionClosedError as error:
				self._record_connection_failure(slot,error)
				raise
			started_at=self._clock()
			try:
				result=operation(slot.client)
			except TransportConnectionClosedError as error:
				self._record_latency(slot,started_at)
				self._record_connection_failure(slot,error)
				raise
			except Exception as error:
				self._record_latency(slot,started_at)
				self._record_operation_failure(slot,error)
				raise
			self._record_latency(slot,started_at)
			self._record_success(slot)
			return result

	def _ensure_connected(self, slot: TransportSlot) -> None:
		if slot.status.online:
			return
		now=self._clock()
		if now < slot.status.next_reconnect_at:
			raise _ReconnectPendingError(
				f"Transport {slot.transport_id} reconnect is allowed at "
				f"{slot.status.next_reconnect_at:.6f}, current time is {now:.6f}",
			)
		if slot._has_connected:
			slot.client.reconnect()
		else:
			slot.client.connect()
			slot._has_connected=True
		slot.status.online=True
		slot.status.next_reconnect_at=0.0

	def _record_latency(self, slot: TransportSlot, started_at: float) -> None:
		slot.status.latency_ms=(self._clock()-started_at)*1000

	def _record_connection_failure(
		self,
		slot: TransportSlot,
		error: TransportConnectionClosedError,
	) -> None:
		slot.status.online=False
		slot.status.last_error=str(error)
		slot.status.error_count+=1
		slot.status.next_reconnect_at=self._clock()+slot.reconnect_delay

	@staticmethod
	def _record_operation_failure(slot: TransportSlot,error: Exception) -> None:
		slot.status.last_error=str(error)
		slot.status.error_count+=1

	@staticmethod
	def _record_success(slot: TransportSlot) -> None:
		slot.status.online=True
		slot.status.last_error=None
		slot.status.error_count=0
		slot.status.next_reconnect_at=0.0
