from __future__ import annotations

import logging
import time
from typing import Protocol

from pysolarmanv5 import PySolarmanV5

from .models import LoggerConfig


LOGGER=logging.getLogger(__name__)


class SolarmanConnectionClosedError(ConnectionError):
	"""The logger has closed its TCP session and requires a fresh client."""


def is_connection_closed_error(error: Exception) -> bool:
	message=str(error).lower()
	return "connection already closed" in message or "connection closed on read" in message


class SolarmanClientProtocol(Protocol):
	def read_holding_registers(self, register_addr: int, quantity: int) -> list[int]:
		...

	def disconnect(self) -> None:
		...


class SolarmanClient:
	def __init__(self, config: LoggerConfig) -> None:
		self._config=config
		self._client: SolarmanClientProtocol | None=None

	def connect(self) -> None:
		self.disconnect()
		LOGGER.info(
			"Connecting to Solarman logger host=%s port=%s serial=%s modbus_id=%s",
			self._config.host,
			self._config.port,
			self._config.serial_number,
			self._config.modbus_id,
		)
		self._client=PySolarmanV5(
			address=self._config.host,
			serial=self._config.serial_number,
			port=self._config.port,
			mb_slave_id=self._config.modbus_id,
			socket_timeout=self._config.timeout,
			auto_reconnect=False,
		)

	def disconnect(self) -> None:
		if self._client is None:
			return
		try:
			self._client.disconnect()
		except Exception:
			LOGGER.debug("Disconnect failed", exc_info=True)
		finally:
			self._client=None

	def probe(self, register: int, count: int) -> list[int]:
		return self.read_holding_registers(register, count)

	def read_holding_registers(self, register: int, count: int) -> list[int]:
		if self._client is None:
			self.connect()
		assert self._client is not None
		start=time.perf_counter()
		try:
			return self._client.read_holding_registers(register, count)
		except Exception as error:
			if is_connection_closed_error(error):
				raise SolarmanConnectionClosedError(str(error)) from error
			raise
		finally:
			latency_ms=(time.perf_counter()-start)*1000
			LOGGER.debug("Read register=%s count=%s latency_ms=%.2f", register, count, latency_ms)
