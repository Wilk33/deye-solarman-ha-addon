"""Transport contracts; the core never imports a concrete transport client."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class TransportConnectionClosedError(ConnectionError):
	"""The active transport requires a new connection."""


class TransportProtocolError(RuntimeError):
	"""The active transport returned an explicit protocol error."""


class RegisterTransport(Protocol):
	transport_id: str

	def connect(self) -> None: ...
	def close(self) -> None: ...
	def reconnect(self) -> None: ...
	def read_holding_registers(self, start: int, count: int) -> list[int]: ...


class WritableRegisterTransport(RegisterTransport,Protocol):
	def write_holding_registers(self, start: int, values: list[int]) -> Any: ...


TransportFactory=Callable[[Any],RegisterTransport]
