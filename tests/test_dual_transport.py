import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from pysolarmanv5 import NoSocketAvailableError


ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"packages"))
sys.path.insert(0,str(ROOT/"apps/deye-solarman/src"))

from deye_inverter_core.config import load_config
from deye_inverter_core.models import Rs485Config
from deye_inverter_core.models import SolarmanConfig
from deye_inverter_core.models import TransportPollingConfig
from deye_solarman_diagnostics.rs485 import ModbusRtuTransport
from deye_solarman_diagnostics.solarman import SolarmanClient
from deye_inverter_core.transport import TransportConnectionClosedError
from deye_inverter_core.transport import TransportProtocolError
from deye_inverter_core.transport_manager import TransportManager
from deye_inverter_core.transport_manager import TransportSlot
from deye_inverter_core.transport_manager import TransportStatus


def make_common_options() -> dict[str,object]:
	return {
		"mqtt": {
			"use_supervisor": False,
			"host": "core-mosquitto",
			"port": 1883,
			"username": "",
			"password": "",
			"client_id": "test",
			"base_topic": "deye_solarman",
			"discovery_prefix": "homeassistant",
			"retain": True,
		},
		"inverter": {
			"serial_number": "2507092018",
			"name": "Deye",
			"manufacturer": "Deye",
			"model": "SG05LP3",
		},
		"profiles": {
			"default_profile": [],
			"overrides_file": "/config/user_sensors.yaml",
			"state_file": "/config/runtime_state.json",
			"scan_report_file": "/share/report.json",
		},
		"advanced": {
			"emit_raw_topics": True,
			"emit_scan_report": True,
		},
	}


def make_polling(default_interval: int=60) -> dict[str,object]:
	return {
		"default_interval": default_interval,
		"slow_interval": 600,
		"read_message_spacing": 0.05,
		"batch_gap": 1,
		"max_registers_per_request": 20,
		"publish_unchanged_every": 900,
		"startup_probe_register": 10040,
		"startup_probe_count": 1,
		"allow_reconnect": True,
	}


def load_options(options: dict[str,object]):
	with tempfile.TemporaryDirectory() as directory:
		path=Path(directory)/"options.json"
		path.write_text(json.dumps(options),encoding="utf-8")
		return load_config(path)


def make_rs485_config() -> Rs485Config:
	return Rs485Config(
		enabled=True,
		device="/dev/ttyUSB1",
		baudrate=19200,
		bytesize=8,
		parity="N",
		stopbits=1,
		modbus_id=17,
		timeout=1.5,
		reconnect_delay=7,
		polling=TransportPollingConfig(**make_polling()),
	)


def make_solarman_config() -> SolarmanConfig:
	return SolarmanConfig(
		enabled=True,
		host="192.0.2.10",
		port=8899,
		serial_number=3556142832,
		modbus_id=1,
		timeout=1,
		reconnect_delay=7,
		polling=TransportPollingConfig(**make_polling()),
	)


class FakeModbusResponse:
	def __init__(self, *, registers: list[int] | None=None, error: bool=False) -> None:
		self.registers=registers
		self._error=error

	def isError(self) -> bool:
		return self._error


class FakeModbusSerialClient:
	def __init__(self, *, connect_result: bool=True) -> None:
		self.connected=False
		self.connect_result=connect_result
		self.close_calls=0
		self.read_calls: list[dict[str,object]]=[]
		self.write_calls: list[dict[str,object]]=[]
		self.read_response=FakeModbusResponse(registers=[101,202])
		self.write_response=FakeModbusResponse()
		self.read_error: Exception | None=None
		self.write_error: Exception | None=None

	def connect(self) -> bool:
		self.connected=self.connect_result
		return self.connect_result

	def close(self) -> None:
		self.close_calls+=1
		self.connected=False

	def read_holding_registers(self, **kwargs: object) -> FakeModbusResponse:
		self.read_calls.append(kwargs)
		if self.read_error is not None:
			raise self.read_error
		return self.read_response

	def write_registers(self, **kwargs: object) -> FakeModbusResponse:
		self.write_calls.append(kwargs)
		if self.write_error is not None:
			raise self.write_error
		return self.write_response


class RecordingModbusClientFactory:
	def __init__(self, clients: list[FakeModbusSerialClient]) -> None:
		self.clients=clients
		self.calls: list[dict[str,object]]=[]

	def __call__(self, **kwargs: object) -> FakeModbusSerialClient:
		self.calls.append(kwargs)
		return self.clients[len(self.calls)-1]


class ManualClock:
	def __init__(self, value: float=0.0) -> None:
		self.value=value

	def __call__(self) -> float:
		return self.value

	def advance(self, seconds: float) -> None:
		self.value+=seconds


class FakeManagedTransport:
	def __init__(self, transport_id: str) -> None:
		self.transport_id=transport_id
		self.connect_calls=0
		self.reconnect_calls=0
		self.close_calls=0
		self.reconnect_error: Exception | None=None

	def connect(self) -> None:
		self.connect_calls+=1

	def reconnect(self) -> None:
		self.reconnect_calls+=1
		if self.reconnect_error is not None:
			raise self.reconnect_error

	def close(self) -> None:
		self.close_calls+=1

	def read_holding_registers(self, start: int, count: int) -> list[int]:
		return [start,count]


class FakeSolarmanLibraryClient:
	def __init__(self) -> None:
		self.disconnect_calls=0

	def disconnect(self) -> None:
		self.disconnect_calls+=1


def make_transport_slot(
	transport_id: str,
	*,
	default_interval: int=60,
	reconnect_delay: float=10.0,
) -> TransportSlot:
	return TransportSlot(
		client=FakeManagedTransport(transport_id),
		polling=TransportPollingConfig(**make_polling(default_interval)),
		reconnect_delay=reconnect_delay,
	)


class DualTransportConfigTests(unittest.TestCase):
	def test_loads_version_2_transport_sections_with_independent_polling(self) -> None:
		options=make_common_options()
		options["solarman"]={
			"enabled": True,
			"host": "192.168.177.144",
			"port": 8899,
			"serial_number": 3556142832,
			"modbus_id": 1,
			"timeout": 3,
			"reconnect_delay": 10,
			"polling": make_polling(61),
		}
		options["rs485"]={
			"enabled": True,
			"device": "/dev/ttyUSB1",
			"baudrate": 19200,
			"bytesize": 8,
			"parity": "N",
			"stopbits": 1,
			"modbus_id": 2,
			"timeout": 1,
			"reconnect_delay": 7,
			"polling": make_polling(13),
		}

		config=load_options(options)

		self.assertIsInstance(config.solarman,SolarmanConfig)
		self.assertIsInstance(config.rs485,Rs485Config)
		self.assertIsInstance(config.solarman.polling,TransportPollingConfig)
		self.assertEqual(config.solarman.host,"192.168.177.144")
		self.assertEqual(config.solarman.polling.default_interval,61)
		self.assertEqual(config.rs485.device,"/dev/ttyUSB1")
		self.assertEqual(config.rs485.baudrate,19200)
		self.assertEqual(config.rs485.modbus_id,2)
		self.assertEqual(config.rs485.polling.default_interval,13)

	def test_migrates_version_1_logger_and_polling_to_solarman(self) -> None:
		options=make_common_options()
		options["logger"]={
			"host": "192.168.177.144",
			"port": 8899,
			"serial_number": 3556142832,
			"modbus_id": 1,
			"timeout": 3,
			"reconnect_delay": 10,
		}
		legacy_polling=make_polling(73)
		legacy_polling.update(
			{
				"slow_interval": 731,
				"read_message_spacing": 0.17,
				"batch_gap": 3,
				"max_registers_per_request": 41,
				"publish_unchanged_every": 937,
				"startup_probe_register": 10041,
				"startup_probe_count": 2,
				"allow_reconnect": False,
			}
		)
		options["polling"]=legacy_polling

		config=load_options(options)

		self.assertTrue(config.solarman.enabled)
		self.assertFalse(config.rs485.enabled)
		self.assertEqual(config.solarman.host,"192.168.177.144")
		self.assertEqual(
			config.solarman.polling,
			TransportPollingConfig(
				default_interval=73,
				slow_interval=731,
				read_message_spacing=0.17,
				batch_gap=3,
				max_registers_per_request=41,
				publish_unchanged_every=937,
				startup_probe_register=10041,
				startup_probe_count=2,
				allow_reconnect=False,
			),
		)
		self.assertIs(config.logger,config.solarman)
		self.assertIs(config.polling,config.solarman.polling)

	def test_accepts_rs485_as_the_only_enabled_transport(self) -> None:
		options=make_common_options()
		options["solarman"]={
			"enabled": False,
			"host": "",
			"port": 8899,
			"serial_number": 0,
			"modbus_id": 1,
			"timeout": 3,
			"reconnect_delay": 10,
			"polling": make_polling(),
		}
		options["rs485"]={
			"enabled": True,
			"device": "/dev/ttyUSB0",
			"baudrate": 9600,
			"bytesize": 8,
			"parity": "N",
			"stopbits": 1,
			"modbus_id": 1,
			"timeout": 1,
			"reconnect_delay": 10,
			"polling": make_polling(),
		}

		config=load_options(options)

		self.assertFalse(config.solarman.enabled)
		self.assertTrue(config.rs485.enabled)

	def test_rejects_configuration_with_both_transports_disabled(self) -> None:
		options=make_common_options()
		options["solarman"]={
			"enabled": False,
			"host": "",
			"port": 8899,
			"serial_number": 0,
			"modbus_id": 1,
			"timeout": 3,
			"reconnect_delay": 10,
			"polling": make_polling(),
		}
		options["rs485"]={
			"enabled": False,
			"device": "/dev/ttyUSB0",
			"baudrate": 9600,
			"bytesize": 8,
			"parity": "N",
			"stopbits": 1,
			"modbus_id": 1,
			"timeout": 1,
			"reconnect_delay": 10,
			"polling": make_polling(),
		}

		with self.assertRaisesRegex(ValueError,"at least one transport must be enabled"):
			load_options(options)

	def test_addon_uses_version_2_sections_and_disables_rs485_by_default(self) -> None:
		addon=yaml.safe_load((ROOT/"deye-solarman-diagnostics/config.yaml").read_text(encoding="utf-8"))

		self.assertEqual(addon["version"],"2.0.0")
		self.assertNotIn("logger",addon["options"])
		self.assertNotIn("polling",addon["options"])
		self.assertTrue(addon["options"]["solarman"]["enabled"])
		self.assertFalse(addon["options"]["rs485"]["enabled"])
		self.assertEqual(addon["options"]["rs485"]["device"],"/dev/ttyUSB0")
		self.assertEqual(addon["schema"]["rs485"]["device"],"device(subsystem=tty)")
		self.assertIn("polling",addon["schema"]["solarman"])
		self.assertIn("polling",addon["schema"]["rs485"])


class ModbusRtuTransportTests(unittest.TestCase):
	def test_connect_uses_serial_configuration_without_library_retries(self) -> None:
		client=FakeModbusSerialClient()
		factory=RecordingModbusClientFactory([client])
		transport=ModbusRtuTransport(make_rs485_config(),client_factory=factory)

		transport.connect()

		self.assertEqual(
			factory.calls,
			[{
				"port": "/dev/ttyUSB1",
				"baudrate": 19200,
				"bytesize": 8,
				"parity": "N",
				"stopbits": 1,
				"timeout": 1.5,
				"retries": 0,
			}],
		)
		self.assertEqual(transport.transport_id,"modbus_rtu")

	def test_read_returns_register_list_and_passes_device_id(self) -> None:
		client=FakeModbusSerialClient()
		transport=ModbusRtuTransport(
			make_rs485_config(),
			client_factory=RecordingModbusClientFactory([client]),
		)
		transport.connect()

		values=transport.read_holding_registers(10040,2)

		self.assertEqual(values,[101,202])
		self.assertEqual(
			client.read_calls,
			[{"address": 10040,"count": 2,"device_id": 17}],
		)

	def test_write_uses_one_write_registers_operation_with_device_id(self) -> None:
		client=FakeModbusSerialClient()
		transport=ModbusRtuTransport(
			make_rs485_config(),
			client_factory=RecordingModbusClientFactory([client]),
		)
		transport.connect()

		result=transport.write_holding_registers(128,[25,30])

		self.assertIs(result,client.write_response)
		self.assertEqual(
			client.write_calls,
			[{"address": 128,"values": [25,30],"device_id": 17}],
		)

	def test_protocol_error_responses_raise_transport_error(self) -> None:
		client=FakeModbusSerialClient()
		transport=ModbusRtuTransport(
			make_rs485_config(),
			client_factory=RecordingModbusClientFactory([client]),
		)
		transport.connect()
		client.read_response=FakeModbusResponse(error=True)

		with self.assertRaisesRegex(TransportProtocolError,"read holding registers"):
			transport.read_holding_registers(10040,1)

		client.write_response=FakeModbusResponse(error=True)
		with self.assertRaisesRegex(TransportProtocolError,"write holding registers"):
			transport.write_holding_registers(128,[25])

	def test_read_io_error_with_stale_connected_flag_requests_reconnect(self) -> None:
		client=FakeModbusSerialClient()
		client.read_error=OSError("USB device disappeared")
		transport=ModbusRtuTransport(
			make_rs485_config(),
			client_factory=RecordingModbusClientFactory([client]),
		)
		transport.connect()

		with self.assertRaisesRegex(TransportConnectionClosedError,"USB device disappeared"):
			transport.read_holding_registers(10040,1)

		self.assertTrue(client.connected)
		self.assertEqual(len(client.read_calls),1)

	def test_write_io_error_with_stale_connected_flag_is_not_retried(self) -> None:
		client=FakeModbusSerialClient()
		client.write_error=OSError("serial port write failed")
		transport=ModbusRtuTransport(
			make_rs485_config(),
			client_factory=RecordingModbusClientFactory([client]),
		)
		transport.connect()

		with self.assertRaisesRegex(TransportConnectionClosedError,"serial port write failed"):
			transport.write_holding_registers(128,[25])

		self.assertTrue(client.connected)
		self.assertEqual(len(client.write_calls),1)

	def test_operations_require_an_active_connection(self) -> None:
		client=FakeModbusSerialClient()
		transport=ModbusRtuTransport(
			make_rs485_config(),
			client_factory=RecordingModbusClientFactory([client]),
		)

		with self.assertRaisesRegex(TransportConnectionClosedError,"not connected"):
			transport.read_holding_registers(10040,1)

		transport.connect()
		client.connected=False
		with self.assertRaisesRegex(TransportConnectionClosedError,"connection is closed"):
			transport.write_holding_registers(128,[25])

	def test_failed_connect_raises_transport_connection_error(self) -> None:
		client=FakeModbusSerialClient(connect_result=False)
		transport=ModbusRtuTransport(
			make_rs485_config(),
			client_factory=RecordingModbusClientFactory([client]),
		)

		with self.assertRaisesRegex(TransportConnectionClosedError,"Could not connect"):
			transport.connect()

		self.assertEqual(client.close_calls,1)

	def test_reconnect_closes_old_client_and_creates_a_new_one(self) -> None:
		first=FakeModbusSerialClient()
		second=FakeModbusSerialClient()
		factory=RecordingModbusClientFactory([first,second])
		transport=ModbusRtuTransport(make_rs485_config(),client_factory=factory)
		transport.connect()

		transport.reconnect()
		transport.read_holding_registers(10040,1)

		self.assertEqual(first.close_calls,1)
		self.assertEqual(len(factory.calls),2)
		self.assertEqual(second.read_calls,[{"address": 10040,"count": 1,"device_id": 17}])

	def test_addon_grants_uart_and_pins_pymodbus(self) -> None:
		addon=yaml.safe_load((ROOT/"deye-solarman-diagnostics/config.yaml").read_text(encoding="utf-8"))
		requirements=(ROOT/"deye-solarman-diagnostics/rootfs/requirements.txt").read_text(encoding="utf-8").splitlines()

		self.assertIs(addon["uart"],True)
		self.assertIn("pymodbus==3.14.0",requirements)


class SolarmanConnectionTests(unittest.TestCase):
	def test_first_connect_failure_is_normalized_and_rate_limited_by_manager(self) -> None:
		clock=ManualClock(100.0)
		client=SolarmanClient(make_solarman_config())
		slot=TransportSlot(
			client=client,
			polling=make_solarman_config().polling,
			reconnect_delay=7,
		)
		manager=TransportManager([slot],clock=clock)
		operations=0
		library_client=FakeSolarmanLibraryClient()

		def operation(received: SolarmanClient) -> str:
			nonlocal operations
			operations+=1
			return received.transport_id

		with patch(
			"deye_solarman_diagnostics.solarman.PySolarmanV5",
			side_effect=[NoSocketAvailableError("No socket available"),library_client],
		) as factory:
			with self.assertRaisesRegex(TransportConnectionClosedError,"No socket available"):
				manager.run("solarman_tcp",operation)

			self.assertFalse(slot.online)
			self.assertEqual(slot.last_error,"No socket available")
			self.assertEqual(slot.error_count,1)
			self.assertEqual(slot.next_reconnect_at,107.0)
			self.assertEqual(factory.call_count,1)
			self.assertEqual(operations,0)

			clock.advance(6.9)
			with self.assertRaisesRegex(TransportConnectionClosedError,"reconnect"):
				manager.run("solarman_tcp",operation)

			self.assertEqual(factory.call_count,1)
			self.assertEqual(operations,0)

			clock.advance(0.1)
			result=manager.run("solarman_tcp",operation)

		self.assertEqual(result,"solarman_tcp")
		self.assertEqual(factory.call_count,2)
		self.assertEqual(operations,1)
		self.assertTrue(slot.online)
		self.assertEqual(slot.error_count,0)
		self.assertIsNone(slot.last_error)

	def test_connect_does_not_reclassify_protocol_error(self) -> None:
		client=SolarmanClient(make_solarman_config())
		error=TransportProtocolError("invalid frame")

		with patch("deye_solarman_diagnostics.solarman.PySolarmanV5",side_effect=error):
			with self.assertRaises(TransportProtocolError) as raised:
				client.connect()

		self.assertIs(raised.exception,error)


class TransportManagerTests(unittest.TestCase):
	def test_slots_have_independent_locks_polling_and_reconnect_delays(self) -> None:
		solarman=make_transport_slot("solarman_tcp",default_interval=61,reconnect_delay=11)
		rs485=make_transport_slot("modbus_rtu",default_interval=13,reconnect_delay=7)
		manager=TransportManager([solarman,rs485])

		self.assertIsNot(solarman.lock,rs485.lock)
		self.assertEqual(manager.get("solarman_tcp").polling.default_interval,61)
		self.assertEqual(manager.get("solarman_tcp").reconnect_delay,11)
		self.assertEqual(manager.get("modbus_rtu").polling.default_interval,13)
		self.assertEqual(manager.get("modbus_rtu").reconnect_delay,7)
		self.assertIsInstance(solarman.status,TransportStatus)

	def test_available_preserves_configuration_order_for_single_and_dual_modes(self) -> None:
		rs485=make_transport_slot("modbus_rtu")
		solarman=make_transport_slot("solarman_tcp")

		dual=TransportManager([rs485,solarman])
		single=TransportManager([solarman])

		self.assertEqual([slot.transport_id for slot in dual.available()],["modbus_rtu","solarman_tcp"])
		self.assertEqual([slot.transport_id for slot in single.available()],["solarman_tcp"])

	def test_first_run_connects_before_executing_operation(self) -> None:
		slot=make_transport_slot("solarman_tcp")
		manager=TransportManager([slot])
		events: list[str]=[]
		client=slot.client

		def operation(received: FakeManagedTransport) -> str:
			self.assertIs(received,client)
			events.append("operation")
			return "value"

		original_connect=client.connect
		def connect() -> None:
			events.append("connect")
			original_connect()
		client.connect=connect

		result=manager.run("solarman_tcp",operation)

		self.assertEqual(result,"value")
		self.assertEqual(events,["connect","operation"])
		self.assertTrue(slot.online)

	def test_connection_failure_blocks_until_delay_then_reconnects_future_operation(self) -> None:
		clock=ManualClock(100.0)
		slot=make_transport_slot("solarman_tcp",reconnect_delay=7)
		manager=TransportManager([slot],clock=clock)
		calls=0

		def failing_operation(client: FakeManagedTransport) -> None:
			nonlocal calls
			calls+=1
			raise TransportConnectionClosedError("socket closed")

		with self.assertRaisesRegex(TransportConnectionClosedError,"socket closed"):
			manager.run("solarman_tcp",failing_operation)

		self.assertEqual(calls,1)
		self.assertFalse(slot.online)
		self.assertEqual(slot.error_count,1)
		self.assertEqual(slot.last_error,"socket closed")
		self.assertEqual(slot.next_reconnect_at,107.0)
		self.assertEqual(slot.client.connect_calls,1)
		self.assertEqual(slot.client.reconnect_calls,0)

		clock.advance(6.9)
		with self.assertRaisesRegex(TransportConnectionClosedError,"reconnect"):
			manager.run("solarman_tcp",lambda client: "too early")

		self.assertEqual(slot.client.connect_calls,1)
		self.assertEqual(slot.client.reconnect_calls,0)
		self.assertEqual(slot.error_count,1)

		clock.advance(0.1)
		result=manager.run("solarman_tcp",lambda client: "recovered")

		self.assertEqual(result,"recovered")
		self.assertEqual(slot.client.connect_calls,1)
		self.assertEqual(slot.client.reconnect_calls,1)
		self.assertTrue(slot.online)
		self.assertEqual(slot.error_count,0)
		self.assertIsNone(slot.last_error)

	def test_reconnect_failure_records_new_delay_without_running_operation(self) -> None:
		clock=ManualClock(20.0)
		slot=make_transport_slot("solarman_tcp",reconnect_delay=5)
		manager=TransportManager([slot],clock=clock)
		manager.run("solarman_tcp",lambda client: "connected")

		with self.assertRaisesRegex(TransportConnectionClosedError,"socket closed"):
			manager.run(
				"solarman_tcp",
				lambda client: (_ for _ in ()).throw(TransportConnectionClosedError("socket closed")),
			)

		clock.advance(5)
		slot.client.reconnect_error=TransportConnectionClosedError("reconnect failed")
		operations=0

		def operation(client: FakeManagedTransport) -> None:
			nonlocal operations
			operations+=1

		with self.assertRaisesRegex(TransportConnectionClosedError,"reconnect failed"):
			manager.run("solarman_tcp",operation)

		self.assertEqual(operations,0)
		self.assertFalse(slot.online)
		self.assertEqual(slot.error_count,2)
		self.assertEqual(slot.last_error,"reconnect failed")
		self.assertEqual(slot.next_reconnect_at,30.0)
		self.assertEqual(slot.client.reconnect_calls,1)

		clock.advance(4.9)
		with self.assertRaisesRegex(TransportConnectionClosedError,"reconnect"):
			manager.run("solarman_tcp",operation)

		self.assertEqual(slot.client.reconnect_calls,1)
		self.assertEqual(operations,0)

		clock.advance(0.1)
		slot.client.reconnect_error=None
		manager.run("solarman_tcp",operation)

		self.assertEqual(slot.client.reconnect_calls,2)
		self.assertEqual(operations,1)
		self.assertTrue(slot.online)

	def test_failed_transport_does_not_stop_other_transport(self) -> None:
		clock=ManualClock()
		solarman=make_transport_slot("solarman_tcp",reconnect_delay=11)
		rs485=make_transport_slot("modbus_rtu",reconnect_delay=7)
		manager=TransportManager([solarman,rs485],clock=clock)

		with self.assertRaisesRegex(TransportConnectionClosedError,"logger offline"):
			manager.run(
				"solarman_tcp",
				lambda client: (_ for _ in ()).throw(TransportConnectionClosedError("logger offline")),
			)

		result=manager.run("modbus_rtu",lambda client: client.transport_id)

		self.assertEqual(result,"modbus_rtu")
		self.assertFalse(solarman.online)
		self.assertTrue(rs485.online)
		self.assertEqual(solarman.next_reconnect_at,11.0)
		self.assertEqual(rs485.next_reconnect_at,0.0)

	def test_blocked_operation_on_one_slot_does_not_block_other_slot(self) -> None:
		solarman=make_transport_slot("solarman_tcp")
		rs485=make_transport_slot("modbus_rtu")
		manager=TransportManager([solarman,rs485])
		first_started=threading.Event()
		release_first=threading.Event()
		second_finished=threading.Event()
		errors: list[BaseException]=[]

		def first_operation(client: FakeManagedTransport) -> None:
			first_started.set()
			if not release_first.wait(2):
				raise TimeoutError("first operation was not released")

		def run_first() -> None:
			try:
				manager.run("solarman_tcp",first_operation)
			except BaseException as error:
				errors.append(error)

		def run_second() -> None:
			try:
				manager.run("modbus_rtu",lambda client: second_finished.set())
			except BaseException as error:
				errors.append(error)

		first_thread=threading.Thread(target=run_first)
		second_thread=threading.Thread(target=run_second)
		first_thread.start()
		try:
			self.assertTrue(first_started.wait(1))
			second_thread.start()
			self.assertTrue(second_finished.wait(1))
		finally:
			release_first.set()
			first_thread.join(2)
			second_thread.join(2)

		self.assertFalse(first_thread.is_alive())
		self.assertFalse(second_thread.is_alive())
		self.assertEqual(errors,[])

	def test_operations_on_same_slot_are_serialized(self) -> None:
		class ObservedRLock:
			def __init__(self) -> None:
				self._lock=threading.RLock()
				self._counter_lock=threading.Lock()
				self._enter_count=0
				self.second_enter_attempted=threading.Event()

			def __enter__(self) -> object:
				with self._counter_lock:
					self._enter_count+=1
					if self._enter_count == 2:
						self.second_enter_attempted.set()
				self._lock.acquire()
				return self

			def __exit__(self, *args: object) -> None:
				self._lock.release()

		observed_lock=ObservedRLock()
		slot=TransportSlot(
			client=FakeManagedTransport("solarman_tcp"),
			polling=TransportPollingConfig(**make_polling()),
			reconnect_delay=10,
			lock=observed_lock,
		)
		manager=TransportManager([slot])
		first_started=threading.Event()
		release_first=threading.Event()
		second_started=threading.Event()
		errors: list[BaseException]=[]

		def first_operation(client: FakeManagedTransport) -> None:
			first_started.set()
			if not release_first.wait(2):
				raise TimeoutError("first operation was not released")

		def run_first() -> None:
			try:
				manager.run("solarman_tcp",first_operation)
			except BaseException as error:
				errors.append(error)

		def run_second() -> None:
			try:
				manager.run("solarman_tcp",lambda client: second_started.set())
			except BaseException as error:
				errors.append(error)

		first_thread=threading.Thread(target=run_first)
		second_thread=threading.Thread(target=run_second)
		first_thread.start()
		try:
			self.assertTrue(first_started.wait(1))
			second_thread.start()
			self.assertTrue(observed_lock.second_enter_attempted.wait(1))
			self.assertFalse(second_started.is_set())
		finally:
			release_first.set()
			first_thread.join(2)
			second_thread.join(2)

		self.assertTrue(second_started.is_set())
		self.assertFalse(first_thread.is_alive())
		self.assertFalse(second_thread.is_alive())
		self.assertEqual(errors,[])

	def test_latency_is_measured_per_slot_with_injected_monotonic_clock(self) -> None:
		clock=ManualClock(20.0)
		solarman=make_transport_slot("solarman_tcp")
		rs485=make_transport_slot("modbus_rtu")
		manager=TransportManager([solarman,rs485],clock=clock)

		def solarman_operation(client: FakeManagedTransport) -> None:
			clock.advance(0.125)

		def rs485_operation(client: FakeManagedTransport) -> None:
			clock.advance(0.007)

		manager.run("solarman_tcp",solarman_operation)
		manager.run("modbus_rtu",rs485_operation)

		self.assertAlmostEqual(solarman.latency_ms,125.0)
		self.assertAlmostEqual(rs485.latency_ms,7.0)

	def test_protocol_error_does_not_retry_operation_or_switch_transport(self) -> None:
		solarman=make_transport_slot("solarman_tcp")
		rs485=make_transport_slot("modbus_rtu")
		manager=TransportManager([solarman,rs485])
		calls=[]

		def operation(client: FakeManagedTransport) -> None:
			calls.append(client.transport_id)
			raise TransportProtocolError("invalid response")

		with self.assertRaisesRegex(TransportProtocolError,"invalid response"):
			manager.run("solarman_tcp",operation)

		self.assertEqual(calls,["solarman_tcp"])
		self.assertEqual(solarman.client.connect_calls,1)
		self.assertEqual(solarman.client.reconnect_calls,0)
		self.assertEqual(rs485.client.connect_calls,0)
		self.assertTrue(solarman.online)
		self.assertEqual(solarman.error_count,1)
		self.assertEqual(solarman.last_error,"invalid response")

	def test_unknown_transport_is_rejected(self) -> None:
		manager=TransportManager([make_transport_slot("solarman_tcp")])

		with self.assertRaisesRegex(KeyError,"unknown_transport"):
			manager.get("unknown_transport")
		with self.assertRaisesRegex(KeyError,"unknown_transport"):
			manager.run("unknown_transport",lambda client: None)


if __name__ == "__main__":
	unittest.main()
