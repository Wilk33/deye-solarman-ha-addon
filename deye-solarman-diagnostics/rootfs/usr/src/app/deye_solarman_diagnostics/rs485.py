"""Synchronous Modbus RTU adapter for the shared Deye transport contract."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from typing import Protocol

from deye_inverter_core.models import Rs485Config
from deye_inverter_core.transport import TransportConnectionClosedError
from deye_inverter_core.transport import TransportProtocolError


class ModbusResponseProtocol(Protocol):
	registers: list[int]

	def isError(self) -> bool:
		...


class ModbusSerialClientProtocol(Protocol):
	connected: bool

	def connect(self) -> bool:
		...

	def close(self) -> None:
		...

	def read_holding_registers(
		self,
		*,
		address: int,
		count: int,
		device_id: int,
	) -> ModbusResponseProtocol:
		...

	def write_registers(
		self,
		*,
		address: int,
		values: list[int],
		device_id: int,
	) -> ModbusResponseProtocol:
		...


ModbusClientFactory=Callable[...,ModbusSerialClientProtocol]


def create_modbus_serial_client(**kwargs: Any) -> ModbusSerialClientProtocol:
	from pymodbus.client import ModbusSerialClient

	return ModbusSerialClient(**kwargs)


class ModbusRtuTransport:
	transport_id="modbus_rtu"

	def __init__(
		self,
		config: Rs485Config,
		client_factory: ModbusClientFactory=create_modbus_serial_client,
	) -> None:
		self._config=config
		self._client_factory=client_factory
		self._client: ModbusSerialClientProtocol | None=None

	def connect(self) -> None:
		self.close()
		client=self._client_factory(
			port=self._config.device,
			baudrate=self._config.baudrate,
			bytesize=self._config.bytesize,
			parity=self._config.parity,
			stopbits=self._config.stopbits,
			timeout=self._config.timeout,
			retries=0,
		)
		self._client=client
		try:
			connected=client.connect()
		except Exception as error:
			self.close()
			raise TransportConnectionClosedError(f"Could not connect to RS485 device: {error}") from error
		if not connected:
			self.close()
			raise TransportConnectionClosedError("Could not connect to RS485 device")

	def close(self) -> None:
		if self._client is None:
			return
		try:
			self._client.close()
		finally:
			self._client=None

	def reconnect(self) -> None:
		self.connect()

	def read_holding_registers(self, start: int, count: int) -> list[int]:
		client=self._connected_client()
		try:
			response=client.read_holding_registers(
				address=start,
				count=count,
				device_id=self._config.modbus_id,
			)
		except Exception as error:
			self._raise_if_connection_closed(client,error)
			raise
		if response.isError():
			raise TransportProtocolError(f"Modbus read holding registers failed: {response}")
		registers=getattr(response,"registers",None)
		if registers is None:
			raise TransportProtocolError("Modbus read holding registers response has no registers")
		return list(registers)

	def write_holding_registers(self, start: int, values: list[int]) -> Any:
		client=self._connected_client()
		try:
			response=client.write_registers(
				address=start,
				values=values,
				device_id=self._config.modbus_id,
			)
		except Exception as error:
			self._raise_if_connection_closed(client,error)
			raise
		if response.isError():
			raise TransportProtocolError(f"Modbus write holding registers failed: {response}")
		return response

	def _connected_client(self) -> ModbusSerialClientProtocol:
		if self._client is None:
			raise TransportConnectionClosedError("RS485 transport is not connected")
		if not self._client.connected:
			raise TransportConnectionClosedError("RS485 connection is closed")
		return self._client

	@staticmethod
	def _raise_if_connection_closed(client: ModbusSerialClientProtocol,error: Exception) -> None:
		if isinstance(error,OSError) or not client.connected:
			raise TransportConnectionClosedError(f"RS485 connection failed: {error}") from error
