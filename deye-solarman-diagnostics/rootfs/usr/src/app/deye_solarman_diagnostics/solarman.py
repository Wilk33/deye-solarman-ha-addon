from __future__ import annotations

import logging
from typing import Protocol
from typing import Any

from pysolarmanv5 import NoSocketAvailableError
from pysolarmanv5 import PySolarmanV5

from deye_inverter_core.models import LoggerConfig
from deye_inverter_core.transport import TransportConnectionClosedError
from deye_inverter_core.logging_utils import register_operation


LOGGER=logging.getLogger(__name__)


SolarmanConnectionClosedError=TransportConnectionClosedError


def is_connection_closed_error(error: Exception) -> bool:
	message=str(error).lower()
	return "connection already closed" in message or "connection closed on read" in message


class SolarmanClientProtocol(Protocol):
	def read_holding_registers(self, register_addr: int, quantity: int) -> list[int]:
		...

	def disconnect(self) -> None:
		...


class SolarmanClient:
	transport_id="solarman_tcp"

	def close(self) -> None:
		self.disconnect()

	def reconnect(self) -> None:
		self.connect()

	def write_holding_registers(self, start: int, values: list[int]) -> Any:
		return self.write_multiple_holding_registers(start,values)

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
		try:
			self._client=PySolarmanV5(
				address=self._config.host,
				serial=self._config.serial_number,
				port=self._config.port,
				mb_slave_id=self._config.modbus_id,
				socket_timeout=self._config.timeout,
				auto_reconnect=False,
			)
		except (NoSocketAvailableError,ConnectionError,OSError) as error:
			self._client=None
			raise TransportConnectionClosedError(str(error)) from error

	def disconnect(self) -> None:
		if self._client is None:
			return
		try:
			self._client.disconnect()
		except Exception as error:
			LOGGER.debug("Solarman disconnect cleanup ignored error=%s",error)
		finally:
			self._client=None

	def probe(self, register: int, count: int) -> list[int]:
		return self.read_holding_registers(register, count)

	def write_multiple_holding_registers(self, register: int, values: list[int]) -> Any:
		if self._client is None:
			raise ConnectionError("Control requires an established connection")
		with register_operation(LOGGER,self.transport_id,"write_fc16",register,len(values),self._config.modbus_id) as details:
			result=self._client.write_multiple_holding_registers(register,values)
			details["registers"]=values
			return result

	def read_holding_registers(self, register: int, count: int) -> list[int]:
		if self._client is None:
			self.connect()
		assert self._client is not None
		with register_operation(LOGGER,self.transport_id,"read_fc03",register,count,self._config.modbus_id) as details:
			try:
				result=self._client.read_holding_registers(register,count)
				details["registers"]=result
				return result
			except (NoSocketAvailableError,ConnectionError,OSError) as error:
				raise SolarmanConnectionClosedError(str(error)) from error
			except Exception as error:
				if is_connection_closed_error(error):
					raise SolarmanConnectionClosedError(str(error)) from error
				raise
