import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml
from pysolarmanv5 import NoSocketAvailableError


ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"packages"))
sys.path.insert(0,str(ROOT/"apps/deye-solarman/src"))

from deye_inverter_core.config import load_config
from deye_inverter_core.controls import CONTROLS
from deye_inverter_core.controls import ControlService
from deye_inverter_core.controls import set_controls
from deye_inverter_core.custom_sensors import load_custom_sensors
from deye_inverter_core.custom_sensors import save_custom_sensors
from deye_inverter_core.definitions import sensor_from_payload
from deye_inverter_core.models import SensorDefinition
from deye_inverter_core.models import Rs485Config
from deye_inverter_core.models import SolarmanConfig
from deye_inverter_core.models import TransportPollingConfig
from deye_inverter_core.main import build_transport_manager
from deye_inverter_core.scan_catalog import ScanCandidate
from deye_inverter_core.scheduler import PerEntityScheduler
from deye_inverter_core.scheduler import group_sensors_for_read
from deye_inverter_core.scanner import save_detected_sensors
from deye_inverter_core.scanner import _read_error_status
from deye_inverter_core.scanner import load_detected_sensors
from deye_inverter_core.scanner import load_monitored_definitions
from deye_inverter_core.scanner import reset_detected_sensors
from deye_inverter_core.scanner import scan_transports_sequentially
from deye_inverter_core.scanner import update_detected_sensors
from deye_solarman_diagnostics.rs485 import ModbusRtuTransport
from deye_solarman_diagnostics.solarman import SolarmanClient
from deye_inverter_core.transport import TransportConnectionClosedError
from deye_inverter_core.transport import TransportProtocolError
from deye_inverter_core.transport_manager import TransportManager
from deye_inverter_core.transport_manager import TransportSlot
from deye_inverter_core.transport_manager import TransportStatus
from deye_inverter_core.transport_runtime import TransportWorker


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


class SequentialScanTransport(FakeManagedTransport):
	def __init__(self, transport_id: str, events: list[str], values: dict[int,int] | None=None) -> None:
		super().__init__(transport_id)
		self.events=events
		self.values=values or {}
		self.failures: dict[int,Exception]={}
		self.active_counter=[0]
		self.writes=[]

	def read_holding_registers(self, start: int, count: int) -> list[int]:
		if self.active_counter[0]:
			raise AssertionError("transport scans overlapped")
		self.active_counter[0]+=1
		self.events.append(f"{self.transport_id}:start")
		try:
			if start in self.failures:
				raise self.failures[start]
			return [self.values.get(address,0) for address in range(start,start+count)]
		finally:
			self.events.append(f"{self.transport_id}:end")
			self.active_counter[0]-=1

	def write_holding_registers(self, start: int, values: list[int]) -> None:
		self.writes.append((start,values))
		raise AssertionError("scan must never write registers")


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


def make_runtime_sensor(
	key: str,
	*,
	transport: str="solarman_tcp",
	read_every: int=60,
	schedule: str="default",
) -> SensorDefinition:
	return SensorDefinition(
		key=key,
		name=key,
		registers=[10040],
		register_type="uint16",
		transport=transport,
		read_every=read_every,
		schedule=schedule,
	)


class RecordingTransportManager(TransportManager):
	def __init__(self, slots: list[TransportSlot], *, clock: ManualClock) -> None:
		super().__init__(slots,clock=clock)
		self.run_transport_ids: list[str]=[]

	def run(self, transport_id: str, operation, *, before_io=None):
		self.run_transport_ids.append(transport_id)
		return super().run(transport_id,operation,before_io=before_io)


class DualTransportConfigTests(unittest.TestCase):
	def test_runtime_builds_only_enabled_transport_slots_for_all_three_modes(self) -> None:
		class RecordingFactory:
			def __init__(self, transport_id: str) -> None:
				self.transport_id=transport_id
				self.configs=[]

			def __call__(self, config):
				self.configs.append(config)
				return FakeManagedTransport(self.transport_id)

		for solarman_enabled,rs485_enabled,expected in (
			(True,False,["solarman_tcp"]),
			(False,True,["modbus_rtu"]),
			(True,True,["solarman_tcp","modbus_rtu"]),
		):
			with self.subTest(solarman=solarman_enabled,rs485=rs485_enabled):
				solarman=make_solarman_config()
				rs485=make_rs485_config()
				solarman.enabled=solarman_enabled
				rs485.enabled=rs485_enabled
				config=SimpleNamespace(solarman=solarman,rs485=rs485)
				solarman_factory=RecordingFactory("solarman_tcp")
				rs485_factory=RecordingFactory("modbus_rtu")

				manager=build_transport_manager(config,solarman_factory,rs485_factory)

				self.assertEqual([slot.transport_id for slot in manager.available()],expected)
				self.assertEqual(solarman_factory.configs,[solarman] if solarman_enabled else [])
				self.assertEqual(rs485_factory.configs,[rs485] if rs485_enabled else [])

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

		self.assertEqual(addon["version"],"2.0.3")
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
	def test_close_continues_after_one_slot_fails(self) -> None:
		first=make_transport_slot("solarman_tcp")
		second=make_transport_slot("modbus_rtu")
		def fail_close():
			first.client.close_calls+=1
			raise RuntimeError("first close failed")
		first.client.close=fail_close
		manager=TransportManager([first,second])

		with self.assertRaisesRegex(RuntimeError,"first close failed"):
			manager.close()

		self.assertEqual(first.client.close_calls,1)
		self.assertEqual(second.client.close_calls,1)
		self.assertFalse(first.online)
		self.assertFalse(second.online)

	def test_close_waits_for_active_slot_operation_and_closes_under_the_same_lock(self) -> None:
		slot=make_transport_slot("modbus_rtu")
		manager=TransportManager([slot])
		operation_started=threading.Event()
		release=threading.Event()
		closed=threading.Event()
		original_close=slot.client.close
		def close():
			original_close()
			closed.set()
		slot.client.close=close
		def operation(client):
			operation_started.set()
			if not release.wait(5):
				raise TimeoutError("test did not release operation")

		worker=threading.Thread(target=lambda:manager.run("modbus_rtu",operation))
		closer=threading.Thread(target=manager.close)
		worker.start()
		self.assertTrue(operation_started.wait(5))
		closer.start()
		self.assertFalse(closed.wait(0.1))
		release.set()
		worker.join(5)
		closer.join(5)

		self.assertTrue(closed.is_set())
		self.assertEqual(slot.client.close_calls,1)
		self.assertFalse(slot.online)

	def test_before_io_guard_runs_inside_slot_lock_before_connect(self) -> None:
		slot=make_transport_slot("modbus_rtu")
		manager=TransportManager([slot])

		with self.assertRaisesRegex(ValueError,"expired"):
			manager.run(
				"modbus_rtu",
				lambda client:self.fail("operation must not run"),
				before_io=lambda:(_ for _ in ()).throw(ValueError("expired")),
			)

		self.assertEqual(slot.client.connect_calls,0)

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


class PerEntitySchedulerTests(unittest.TestCase):
	def test_read_every_shorter_than_transport_default_runs_at_each_sensor_deadline(self) -> None:
		clock=ManualClock()
		sensor=make_runtime_sensor("fast",read_every=1)
		scheduler=PerEntityScheduler(
			[sensor],
			TransportPollingConfig(**make_polling(5)),
			clock=clock,
		)

		self.assertEqual(scheduler.next_due,0.0)
		self.assertEqual([item.key for item in scheduler.due(clock())],["fast"])
		scheduler.mark_read("fast",clock())
		self.assertEqual(scheduler.next_due,1.0)

		clock.advance(1)
		self.assertEqual([item.key for item in scheduler.due(clock())],["fast"])
		scheduler.mark_read("fast",clock())
		self.assertEqual(scheduler.next_due,2.0)

		clock.advance(1)
		self.assertEqual([item.key for item in scheduler.due(clock())],["fast"])

	def test_read_every_longer_than_transport_default_is_not_shortened(self) -> None:
		clock=ManualClock(10.0)
		sensor=make_runtime_sensor("slow_explicit",read_every=60)
		scheduler=PerEntityScheduler(
			[sensor],
			TransportPollingConfig(**make_polling(5)),
			clock=clock,
		)

		scheduler.mark_read(sensor.key,clock())
		clock.advance(59.9)

		self.assertEqual(scheduler.due(clock()),())
		self.assertAlmostEqual(scheduler.wait_time(clock()),0.1)
		clock.advance(0.1)
		self.assertEqual([item.key for item in scheduler.due(clock())],[sensor.key])

	def test_legacy_slow_sensor_uses_slow_interval_but_distinct_value_is_explicit(self) -> None:
		clock=ManualClock()
		legacy=make_runtime_sensor("legacy_slow",schedule="slow")
		explicit=make_runtime_sensor("explicit_slow",schedule="slow",read_every=300)
		polling=TransportPollingConfig(**make_polling(5))
		scheduler=PerEntityScheduler([legacy,explicit],polling,clock=clock)

		scheduler.mark_read(legacy.key,clock())
		scheduler.mark_read(explicit.key,clock())

		self.assertEqual(scheduler.next_due,300.0)
		clock.advance(300)
		self.assertEqual([item.key for item in scheduler.due(clock())],[explicit.key])
		scheduler.mark_read(explicit.key,clock())
		clock.advance(299.9)
		self.assertEqual(scheduler.due(clock()),())
		clock.advance(0.1)
		self.assertEqual([item.key for item in scheduler.due(clock())],[explicit.key,legacy.key])

	def test_sync_preserves_existing_deadline_adds_new_sensor_and_removes_missing_sensor(self) -> None:
		clock=ManualClock(100.0)
		kept=make_runtime_sensor("kept",read_every=30)
		removed=make_runtime_sensor("removed",read_every=10)
		scheduler=PerEntityScheduler(
			[kept,removed],
			TransportPollingConfig(**make_polling()),
			clock=clock,
		)
		scheduler.mark_read(kept.key,clock())
		scheduler.mark_read(removed.key,clock())
		clock.advance(5)
		updated_kept=make_runtime_sensor("kept",read_every=5)
		added=make_runtime_sensor("added",read_every=20)

		scheduler.sync([updated_kept,added],now=clock())

		self.assertEqual(scheduler.next_due,105.0)
		self.assertEqual([item.key for item in scheduler.due(clock())],["added"])
		with self.assertRaises(KeyError):
			scheduler.mark_read("removed",clock())
		scheduler.mark_read("added",clock())
		self.assertEqual(scheduler.next_due,125.0)
		clock.advance(25)
		self.assertEqual([item.key for item in scheduler.due(clock())],["added","kept"])

	def test_close_deadlines_are_coalesced_within_controlled_window(self) -> None:
		clock=ManualClock(10.0)
		first=make_runtime_sensor("first",read_every=5)
		second=make_runtime_sensor("second",read_every=5)
		scheduler=PerEntityScheduler(
			[first,second],
			TransportPollingConfig(**make_polling()),
			clock=clock,
			coalescing_window=0.05,
		)
		scheduler.mark_read(first.key,clock())
		clock.advance(0.04)
		scheduler.mark_read(second.key,clock())

		clock.advance(4.96)

		self.assertEqual([item.key for item in scheduler.due(clock())],["first","second"])

	def test_empty_scheduler_has_no_deadline_or_wait(self) -> None:
		clock=ManualClock(12.0)
		scheduler=PerEntityScheduler(
			[],
			TransportPollingConfig(**make_polling()),
			clock=clock,
		)

		self.assertIsNone(scheduler.next_due)
		self.assertIsNone(scheduler.wait_time(clock()))
		self.assertEqual(scheduler.due(clock()),())


class TransportWorkerTests(unittest.TestCase):
	def test_worker_marks_only_groups_reported_as_attempted_before_connection_error(self) -> None:
		clock=ManualClock(30.0)
		slot=make_transport_slot("solarman_tcp",reconnect_delay=7)
		manager=RecordingTransportManager([slot],clock=clock)
		first=make_runtime_sensor("first",read_every=5)
		first.registers=[10040]
		second=make_runtime_sensor("second",read_every=5)
		second.registers=[10050]
		scheduler=PerEntityScheduler([first,second],slot.polling,clock=clock)
		def read_first_group_then_fail(client, sensors, mark_attempted):
			groups=group_sensors_for_read(list(sensors),slot.polling)
			self.assertEqual([[sensor.key for sensor in group] for group in groups],[["first"],["second"]])
			mark_attempted(sensor.key for sensor in groups[0])
			raise TransportConnectionClosedError("connection lost after first group")
		worker=TransportWorker(manager,slot,scheduler,read_first_group_then_fail,clock=clock)

		with self.assertRaisesRegex(TransportConnectionClosedError,"connection lost after first group"):
			worker.run_due(clock())

		self.assertEqual([sensor.key for sensor in scheduler.due(30.0)],["second"])
		self.assertEqual([sensor.key for sensor in scheduler.due(34.9)],["second"])
		self.assertEqual([sensor.key for sensor in scheduler.due(35.0)],["second","first"])

	def test_worker_wait_time_ignores_due_sensor_from_another_transport(self) -> None:
		clock=ManualClock()
		slot=make_transport_slot("solarman_tcp")
		manager=RecordingTransportManager([slot],clock=clock)
		own=make_runtime_sensor("own",transport="solarman_tcp",read_every=5)
		foreign=make_runtime_sensor("foreign",transport="modbus_rtu",read_every=1)
		scheduler=PerEntityScheduler([own,foreign],slot.polling,clock=clock)
		scheduler.mark_read("own",clock())
		worker=TransportWorker(
			manager,
			slot,
			scheduler,
			lambda client,sensors,mark_attempted: None,
			clock=clock,
		)

		self.assertEqual(worker.wait_time(clock()),5.0)

	def test_workers_keep_independent_transport_deadlines(self) -> None:
		clock=ManualClock()
		solarman_slot=make_transport_slot("solarman_tcp",default_interval=5)
		rs485_slot=make_transport_slot("modbus_rtu",default_interval=30)
		manager=RecordingTransportManager([solarman_slot,rs485_slot],clock=clock)
		solarman_scheduler=PerEntityScheduler(
			[make_runtime_sensor("fast",transport="solarman_tcp",read_every=1)],
			solarman_slot.polling,
			clock=clock,
		)
		rs485_scheduler=PerEntityScheduler(
			[make_runtime_sensor("slow",transport="modbus_rtu",read_every=10)],
			rs485_slot.polling,
			clock=clock,
		)
		reads: list[tuple[str,tuple[str,...]]]=[]
		def read(client, sensors, mark_attempted):
			mark_attempted(sensor.key for sensor in sensors)
			reads.append((client.transport_id,tuple(sensor.key for sensor in sensors)))
		solarman_worker=TransportWorker(manager,solarman_slot,solarman_scheduler,read,clock=clock)
		rs485_worker=TransportWorker(manager,rs485_slot,rs485_scheduler,read,clock=clock)

		solarman_worker.run_due(clock())
		rs485_worker.run_due(clock())
		clock.advance(1)
		solarman_worker.run_due(clock())
		rs485_worker.run_due(clock())

		self.assertEqual(
			reads,
			[("solarman_tcp",("fast",)),("modbus_rtu",("slow",)),("solarman_tcp",("fast",))],
		)
		self.assertEqual(manager.run_transport_ids,["solarman_tcp","modbus_rtu","solarman_tcp"])
		self.assertEqual(solarman_worker.wait_time(clock()),1.0)
		self.assertEqual(rs485_worker.wait_time(clock()),9.0)

	def test_worker_runs_one_operation_for_only_its_transport_without_fallback(self) -> None:
		clock=ManualClock()
		solarman_slot=make_transport_slot("solarman_tcp")
		rs485_slot=make_transport_slot("modbus_rtu")
		manager=RecordingTransportManager([solarman_slot,rs485_slot],clock=clock)
		solarman=make_runtime_sensor("solarman",transport="solarman_tcp",read_every=5)
		rs485=make_runtime_sensor("rs485",transport="modbus_rtu",read_every=5)
		scheduler=PerEntityScheduler([solarman,rs485],solarman_slot.polling,clock=clock)
		read_calls=[]
		def fail(client, sensors, mark_attempted):
			mark_attempted(sensor.key for sensor in sensors)
			read_calls.append((client.transport_id,tuple(sensor.key for sensor in sensors)))
			raise TimeoutError("read timeout")
		worker=TransportWorker(manager,solarman_slot,scheduler,fail,clock=clock)

		with self.assertRaisesRegex(TimeoutError,"read timeout"):
			worker.run_due(clock())

		self.assertEqual(read_calls,[("solarman_tcp",("solarman",))])
		self.assertEqual(manager.run_transport_ids,["solarman_tcp"])
		self.assertEqual(solarman_slot.client.connect_calls,1)
		self.assertEqual(rs485_slot.client.connect_calls,0)
		self.assertEqual([item.key for item in scheduler.due(clock())],["rs485"])

	def test_worker_marks_attempt_after_success_and_timeout_to_prevent_tight_loop(self) -> None:
		for error in (None,TimeoutError("read timeout")):
			with self.subTest(error=error):
				clock=ManualClock(20.0)
				slot=make_transport_slot("solarman_tcp")
				manager=RecordingTransportManager([slot],clock=clock)
				sensor=make_runtime_sensor("sensor",read_every=2)
				scheduler=PerEntityScheduler([sensor],slot.polling,clock=clock)
				def read(client, sensors, mark_attempted):
					mark_attempted(sensor.key for sensor in sensors)
					clock.advance(0.5)
					if error is not None:
						raise error
					return tuple(item.key for item in sensors)
				worker=TransportWorker(manager,slot,scheduler,read,clock=clock)

				if error is None:
					self.assertEqual(worker.run_due(20.0),("sensor",))
				else:
					with self.assertRaisesRegex(TimeoutError,"read timeout"):
						worker.run_due(20.0)

				self.assertEqual(worker.run_due(clock()),None)
				self.assertEqual(manager.run_transport_ids,["solarman_tcp"])
				self.assertEqual(scheduler.next_due,22.5)
				self.assertEqual(worker.wait_time(clock()),2.0)

	def test_connect_failure_preserves_sensor_deadline_and_waits_for_reconnect(self) -> None:
		clock=ManualClock(50.0)
		slot=make_transport_slot("solarman_tcp",reconnect_delay=7)
		slot.client.connect=lambda: (_ for _ in ()).throw(TransportConnectionClosedError("offline"))
		manager=RecordingTransportManager([slot],clock=clock)
		sensor=make_runtime_sensor("sensor",read_every=2)
		scheduler=PerEntityScheduler([sensor],slot.polling,clock=clock)
		reads=[]
		worker=TransportWorker(
			manager,
			slot,
			scheduler,
			lambda client,sensors,mark_attempted: reads.append(tuple(item.key for item in sensors)),
			clock=clock,
		)

		with self.assertRaisesRegex(TransportConnectionClosedError,"offline"):
			worker.run_due(clock())

		self.assertEqual(reads,[])
		self.assertEqual(scheduler.next_due,50.0)
		self.assertEqual(worker.wait_time(clock()),7.0)


class EntityTransportSelectionTests(unittest.TestCase):
	def custom_snapshot(self, definition: dict) -> dict:
		sensor=sensor_from_payload(definition)
		return {
			"registers":sensor.registers,
			"type":sensor.register_type,
			"formula":sensor.formula,
			"multiplier":sensor.multiplier,
			"offset":sensor.offset,
			"word_order":sensor.word_order,
			"byte_order":sensor.byte_order,
			"transport":sensor.transport,
		}

	def candidate(self, *, transports: list[str] | None=None) -> ScanCandidate:
		arguments={}
		if transports is not None:
			arguments["transports"]=transports
		return ScanCandidate(
			SensorDefinition("voltage","Voltage",[10],"uint16",0.1,**arguments),
			"documented",
			"test",
		)

	def manager(
		self,
		solarman: SequentialScanTransport | None,
		rs485: SequentialScanTransport | None,
	) -> TransportManager:
		slots=[]
		for transport in (solarman,rs485):
			if transport is not None:
				slots.append(
					TransportSlot(
						transport,
						TransportPollingConfig(**make_polling()),
						10,
					)
				)
		return TransportManager(slots)

	def test_sensor_model_defaults_legacy_payload_to_solarman_and_both_transports(self) -> None:
		sensor=sensor_from_payload({"key":"voltage","registers":[10],"type":"uint16"})

		self.assertEqual(sensor.transport,"solarman_tcp")
		self.assertEqual(sensor.transports,["solarman_tcp","modbus_rtu"])
		rs485_only=sensor_from_payload({
			"key":"rs485_voltage",
			"registers":[11],
			"type":"uint16",
			"transports":["modbus_rtu"],
		})
		self.assertEqual(rs485_only.transport,"modbus_rtu")

	def test_sensor_model_rejects_duplicate_unknown_or_unselected_transport(self) -> None:
		invalid=(
			{"transport":"solarman_tcp","transports":[]},
			{"transport":"solarman_tcp","transports":["solarman_tcp","solarman_tcp"]},
			{"transport":"serial","transports":["serial"]},
			{"transport":"modbus_rtu","transports":["solarman_tcp"]},
		)
		for fields in invalid:
			with self.subTest(fields=fields),self.assertRaises(ValueError):
				sensor_from_payload({"key":"voltage","registers":[10],"type":"uint16",**fields})

	def test_dual_supported_scan_is_sequential_and_preserves_rs485_selection(self) -> None:
		events=[]
		solarman=SequentialScanTransport("solarman_tcp",events,{10:500})
		rs485=SequentialScanTransport("modbus_rtu",events,{10:501})
		shared_counter=[0]
		solarman.active_counter=shared_counter
		rs485.active_counter=shared_counter
		previous=[{"key":"voltage","definition":{"transport":"modbus_rtu"}}]

		entry=scan_transports_sequentially([self.candidate()],self.manager(solarman,rs485),previous)[0]

		self.assertEqual(events,["solarman_tcp:start","solarman_tcp:end","modbus_rtu:start","modbus_rtu:end"])
		self.assertEqual(entry["status"],"supported")
		self.assertEqual(entry["definition"]["transport"],"modbus_rtu")
		self.assertEqual(entry["definition"]["transports"],["solarman_tcp","modbus_rtu"])
		self.assertEqual(entry["last_scan"]["solarman_tcp"]["status"],"supported")
		self.assertEqual(entry["last_scan"]["modbus_rtu"]["status"],"supported")

	def test_scan_selects_the_only_supported_transport_and_defaults_new_dual_to_solarman(self) -> None:
		for supported,expected in (("solarman_tcp","solarman_tcp"),("modbus_rtu","modbus_rtu")):
			with self.subTest(supported=supported):
				events=[]
				solarman=SequentialScanTransport("solarman_tcp",events,{10:500})
				rs485=SequentialScanTransport("modbus_rtu",events,{10:501})
				failed=rs485 if supported == "solarman_tcp" else solarman
				failed.failures[10]=TimeoutError("offline read")
				entry=scan_transports_sequentially([self.candidate()],self.manager(solarman,rs485))[0]
				self.assertEqual(entry["definition"]["transport"],expected)
				self.assertEqual(entry["last_scan"][supported]["status"],"supported")
		dual=scan_transports_sequentially(
			[self.candidate()],
			self.manager(
				SequentialScanTransport("solarman_tcp",[],{10:500}),
				SequentialScanTransport("modbus_rtu",[],{10:501}),
			),
		)[0]
		self.assertEqual(dual["definition"]["transport"],"solarman_tcp")

	def test_scan_distinguishes_unavailable_unsupported_and_unknown(self) -> None:
		events=[]
		solarman=SequentialScanTransport("solarman_tcp",events)
		solarman.failures[10]=TimeoutError("no reply")
		entry=scan_transports_sequentially([self.candidate()],self.manager(solarman,None))[0]
		self.assertEqual(entry["status"],"unknown")
		self.assertEqual(entry["last_scan"]["solarman_tcp"]["status"],"timeout")
		self.assertEqual(entry["last_scan"]["modbus_rtu"]["status"],"unavailable")

		restricted=scan_transports_sequentially(
			[self.candidate(transports=["solarman_tcp"])],
			self.manager(SequentialScanTransport("solarman_tcp",[],{10:500}),None),
		)[0]
		self.assertEqual(restricted["last_scan"]["modbus_rtu"]["status"],"unsupported")

		events=[]
		rs485=SequentialScanTransport("modbus_rtu",events)
		rs485.failures[10]=TransportProtocolError(
			"Modbus read holding registers failed: ExceptionResponse(dev_id=1, function_code=131, exception_code=2)"
		)
		protocol_unsupported=scan_transports_sequentially(
			[self.candidate()],self.manager(None,rs485),
		)[0]
		self.assertEqual(protocol_unsupported["last_scan"]["modbus_rtu"]["status"],"unsupported")

		class InvalidValueTransport(SequentialScanTransport):
			def read_holding_registers(self, start: int, count: int) -> list[int]:
				self.events.append(f"{self.transport_id}:start")
				self.events.append(f"{self.transport_id}:end")
				return []

		invalid=scan_transports_sequentially(
			[self.candidate()],
			self.manager(InvalidValueTransport("solarman_tcp",[]),None),
		)[0]
		self.assertEqual(invalid["last_scan"]["solarman_tcp"]["status"],"invalid_value")

	def test_detected_sensor_migrates_legacy_scan_and_validates_selection(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			path=Path(directory)/"detected.yaml"
			legacy={
				"version":1,
				"available_sensors":[{
					"key":"voltage",
					"monitor":False,
					"definition":{"key":"voltage","name":"Voltage","registers":[10],"type":"uint16"},
					"last_scan":{"status":"supported","value":50.0,"raw_registers":[500]},
				}],
			}
			path.write_text(yaml.safe_dump(legacy),encoding="utf-8")
			report=scan_transports_sequentially(
				[self.candidate()],
				self.manager(SequentialScanTransport("solarman_tcp",[],{10:500}),None),
				legacy["available_sensors"],
			)
			save_detected_sensors(str(path),report)
			entry=yaml.safe_load(path.read_text(encoding="utf-8"))["available_sensors"][0]
			self.assertEqual(entry["definition"]["transport"],"solarman_tcp")
			self.assertEqual(entry["definition"]["transports"],["solarman_tcp","modbus_rtu"])
			self.assertEqual(entry["last_scan"]["solarman_tcp"]["raw_registers"],[500])
			with self.assertRaisesRegex(ValueError,"transport"):
				update_detected_sensors(str(path),[{"key":"voltage","monitor":False,"definition":{"transport":"modbus_rtu"}}])
			invalid=yaml.safe_load(path.read_text(encoding="utf-8"))
			invalid["available_sensors"][0]["definition"]["transport"]="modbus_rtu"
			path.write_text(yaml.safe_dump(invalid),encoding="utf-8")
			with self.assertRaisesRegex(ValueError,"supported"):
				update_detected_sensors(str(path),[{"key":"voltage","monitor":True,"definition":{}}])

	def test_custom_sensor_persistence_keeps_transport_fields(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			path=Path(directory)/"custom.yaml"
			custom_definition={
				"key":"custom_voltage",
				"registers":[10],
				"type":"uint16",
				"transport":"modbus_rtu",
				"transports":["solarman_tcp","modbus_rtu"],
			}
			payload=save_custom_sensors(str(path),[{
				"key":"custom_voltage",
				"monitor":True,
				"last_scan":{
					"modbus_rtu":{
						"status":"supported",
						"raw_registers":[500],
						"value":500,
						"definition_snapshot":self.custom_snapshot(custom_definition),
					},
				},
				"definition":custom_definition,
			}])
			definition=payload["sensors"][0]["definition"]
			self.assertEqual(definition["transport"],"modbus_rtu")
			self.assertEqual(definition["transports"],["solarman_tcp","modbus_rtu"])

	def test_legacy_sensor_files_load_with_solarman_selection_and_nested_scan(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			detected_path=Path(directory)/"detected.yaml"
			custom_path=Path(directory)/"custom.yaml"
			definition={"key":"voltage","registers":[10],"type":"uint16"}
			detected_path.write_text(yaml.safe_dump({
				"version":1,
				"available_sensors":[{
					"key":"voltage",
					"monitor":True,
					"definition":definition,
					"last_scan":{"status":"supported","raw_registers":[500]},
				}],
			}),encoding="utf-8")
			custom_path.write_text(yaml.safe_dump({
				"version":1,
				"sensors":[{"key":"voltage","monitor":True,"definition":definition}],
			}),encoding="utf-8")

			detected=load_detected_sensors(str(detected_path))["available_sensors"][0]
			custom=load_custom_sensors(str(custom_path))["sensors"][0]

			self.assertEqual(detected["definition"]["transport"],"solarman_tcp")
			self.assertEqual(detected["last_scan"]["solarman_tcp"]["raw_registers"],[500])
			self.assertEqual(custom["definition"]["transport"],"solarman_tcp")
			self.assertEqual(custom["definition"]["transports"],["solarman_tcp","modbus_rtu"])

	def test_control_scan_uses_both_transports_read_only_and_preserves_selection(self) -> None:
		catalog=list(CONTROLS.values())
		control=dict(CONTROLS["control_grid_charge_battery_current"])
		set_controls([control])
		try:
			with tempfile.TemporaryDirectory() as directory:
				events=[]
				solarman=SequentialScanTransport("solarman_tcp",events,{128:37})
				rs485=SequentialScanTransport("modbus_rtu",events,{128:38})
				manager=self.manager(solarman,rs485)
				service=ControlService(
					str(Path(directory)/"controls.json"),
					None,
					threading.Lock(),
					0,
					transport_manager=manager,
				)
				previous=service.entry(control["key"])
				previous["definition"]["transport"]="modbus_rtu"
				service.store({"available_sensors":[previous],"published":[]})

				service._scan(lambda:None)

				entry=service.load()["available_sensors"][0]
				self.assertEqual(entry["definition"]["transport"],"modbus_rtu")
				self.assertEqual(entry["last_scan"]["solarman_tcp"]["status"],"supported")
				self.assertEqual(entry["last_scan"]["modbus_rtu"]["status"],"supported")
				self.assertEqual(solarman.writes+rs485.writes,[])
				self.assertLess(events.index("solarman_tcp:end"),events.index("modbus_rtu:start"))
		finally:
			set_controls(catalog)

	def test_control_scan_uses_each_transport_slot_message_spacing(self) -> None:
		catalog=list(CONTROLS.values())
		control=dict(CONTROLS["control_grid_charge_battery_current"])
		set_controls([control])
		try:
			with tempfile.TemporaryDirectory() as directory:
				events=[]
				solarman=SequentialScanTransport("solarman_tcp",events,{128:37})
				rs485=SequentialScanTransport("modbus_rtu",events,{128:38})
				solarman_polling=TransportPollingConfig(**{**make_polling(),"read_message_spacing":0.11})
				rs485_polling=TransportPollingConfig(**{**make_polling(),"read_message_spacing":0.22})
				manager=TransportManager([
					TransportSlot(solarman,solarman_polling,10),
					TransportSlot(rs485,rs485_polling,10),
				])
				service=ControlService(
					str(Path(directory)/"controls.json"),
					None,
					threading.Lock(),
					0.99,
					transport_manager=manager,
				)
				with patch("deye_inverter_core.controls.time.sleep") as sleep:
					service._scan(lambda:None)

				self.assertEqual([call.args[0] for call in sleep.call_args_list],[0.11,0.22])
		finally:
			set_controls(catalog)

	def test_control_selection_requires_an_allowed_supported_writable_transport(self) -> None:
		catalog=list(CONTROLS.values())
		control=dict(CONTROLS["control_grid_charge_battery_current"])
		set_controls([control])
		try:
			with tempfile.TemporaryDirectory() as directory:
				service=ControlService(str(Path(directory)/"controls.json"),None,threading.Lock(),0)
				entry=service.entry(control["key"])
				branches={
					"solarman_tcp":{"status":"supported","write_allowed":True},
					"modbus_rtu":{"status":"supported","write_allowed":True},
				}
				entry["last_scan"]={**branches,**branches["solarman_tcp"]}
				service.store({"available_sensors":[entry],"published":[]})
				updated=service.update([{
					"key":control["key"],
					"monitor":True,
					"definition":{"transport":"modbus_rtu"},
				}])
				self.assertEqual(updated["available_sensors"][0]["definition"]["transport"],"modbus_rtu")

				entry=updated["available_sensors"][0]
				entry["last_scan"]["solarman_tcp"]={"status":"timeout"}
				service.store(updated)
				with self.assertRaisesRegex(ValueError,"poprawny odczyt"):
					service.update([{
						"key":control["key"],
						"monitor":True,
						"definition":{"transport":"solarman_tcp"},
					}])
		finally:
			set_controls(catalog)

	def test_control_scan_maps_unknown_decoding_to_invalid_value(self) -> None:
		catalog=list(CONTROLS.values())
		control=dict(CONTROLS["control_load_limit"])
		set_controls([control])
		try:
			with tempfile.TemporaryDirectory() as directory:
				service=ControlService(
					str(Path(directory)/"controls.json"),
					None,
					threading.Lock(),
					0,
					transport_manager=self.manager(
						SequentialScanTransport("solarman_tcp",[],{142:99}),
						None,
					),
				)
				service._scan(lambda:None)
				entry=service.load()["available_sensors"][0]
				self.assertEqual(entry["last_scan"]["solarman_tcp"]["status"],"invalid_value")
		finally:
			set_controls(catalog)

	def test_legacy_monitored_timeout_is_migrated_and_skipped_at_startup(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			path=Path(directory)/"detected.yaml"
			path.write_text(yaml.safe_dump({
				"version":1,
				"available_sensors":[{
					"key":"voltage",
					"monitor":True,
					"definition":{"key":"voltage","name":"Voltage","registers":[10],"type":"uint16"},
					"last_scan":{"status":"timeout","error":"legacy timeout"},
				}],
			}),encoding="utf-8")

			self.assertEqual(load_monitored_definitions(str(path)),[])
			loaded=load_detected_sensors(str(path))["available_sensors"][0]
			self.assertFalse(loaded["monitor"])
			self.assertEqual(loaded["last_scan"]["solarman_tcp"]["status"],"timeout")

	def test_sensor_scan_preserves_success_before_connection_closes_and_marks_slot_offline(self) -> None:
		first=self.candidate(transports=["solarman_tcp"])
		second=ScanCandidate(
			SensorDefinition("current","Current",[100],"uint16",1,transports=["solarman_tcp"]),
			"documented",
			"test",
		)
		transport=SequentialScanTransport("solarman_tcp",[],{10:500})
		transport.failures[100]=TransportConnectionClosedError("socket closed")
		manager=self.manager(transport,None)

		entries=scan_transports_sequentially([first,second],manager)

		by_key={entry["key"]:entry for entry in entries}
		self.assertEqual(by_key["voltage"]["last_scan"]["solarman_tcp"]["status"],"supported")
		self.assertEqual(by_key["current"]["last_scan"]["solarman_tcp"]["status"],"unavailable")
		self.assertFalse(manager.get("solarman_tcp").online)

	def test_sensor_all_protocol_failures_are_reported_without_false_slot_success(self) -> None:
		transport=SequentialScanTransport("solarman_tcp",[])
		transport.failures[10]=TransportProtocolError("CRC mismatch")
		manager=self.manager(transport,None)

		entry=scan_transports_sequentially([self.candidate(transports=["solarman_tcp"])],manager)[0]

		self.assertEqual(entry["last_scan"]["solarman_tcp"]["status"],"timeout")
		slot=manager.get("solarman_tcp")
		self.assertEqual(slot.error_count,1)
		self.assertEqual(slot.last_error,"All scan reads failed")
		self.assertTrue(slot.online)

	def test_removed_previous_transport_selects_only_supported_allowed_transport(self) -> None:
		entry=scan_transports_sequentially(
			[self.candidate(transports=["solarman_tcp"])],
			self.manager(SequentialScanTransport("solarman_tcp",[],{10:500}),None),
			[{"key":"voltage","definition":{"transport":"modbus_rtu"}}],
		)[0]

		self.assertEqual(entry["definition"]["transport"],"solarman_tcp")

	def test_custom_register_sensor_requires_and_persists_supported_selected_scan(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			path=Path(directory)/"custom.yaml"
			definition={
				"key":"custom_voltage",
				"registers":[10],
				"type":"uint16",
				"transport":"modbus_rtu",
				"transports":["solarman_tcp","modbus_rtu"],
			}
			with self.assertRaisesRegex(ValueError,"supported scan"):
				save_custom_sensors(str(path),[{"key":"custom_voltage","monitor":False,"definition":definition}])
			last_scan={
				"solarman_tcp":{"status":"timeout"},
				"modbus_rtu":{
					"status":"supported",
					"raw_registers":[500],
					"value":500,
					"definition_snapshot":self.custom_snapshot(definition),
				},
			}
			payload=save_custom_sensors(str(path),[{
				"key":"custom_voltage",
				"monitor":True,
				"definition":definition,
				"last_scan":last_scan,
			}])
			self.assertEqual(payload["sensors"][0]["last_scan"]["modbus_rtu"]["value"],500)
			self.assertEqual(payload["sensors"][0]["last_scan"]["status"],"supported")

	def test_new_custom_sensor_rejects_supported_scan_for_a_different_read_definition(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			path=Path(directory)/"custom.yaml"
			tested_definition={"key":"custom_voltage","registers":[10],"type":"uint16"}
			current_definition={**tested_definition,"registers":[11]}
			entry={
				"key":"custom_voltage",
				"monitor":True,
				"definition":current_definition,
				"last_scan":{"solarman_tcp":{
					"status":"supported",
					"raw_registers":[500],
					"value":500,
					"definition_snapshot":self.custom_snapshot(tested_definition),
				}},
			}

			with self.assertRaisesRegex(ValueError,"current read definition"):
				save_custom_sensors(str(path),[entry])

	def test_existing_custom_sensor_rejects_stale_supported_scan_after_read_change(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			path=Path(directory)/"custom.yaml"
			definition={"key":"custom_voltage","registers":[10],"type":"uint16"}
			initial=save_custom_sensors(str(path),[{
				"key":"custom_voltage",
				"monitor":True,
				"definition":definition,
				"last_scan":{"solarman_tcp":{
					"status":"supported",
					"raw_registers":[500],
					"value":500,
					"definition_snapshot":self.custom_snapshot(definition),
				}},
			}])["sensors"][0]
			initial["definition"]["type"]="int16"

			with self.assertRaisesRegex(ValueError,"current read definition"):
				save_custom_sensors(str(path),[initial])

	def test_failed_custom_sensor_retest_blocks_save_and_panel_preserves_history(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			path=Path(directory)/"custom.yaml"
			definition={"key":"custom_voltage","registers":[10],"type":"uint16"}
			entry={
				"key":"custom_voltage",
				"monitor":True,
				"definition":definition,
				"last_scan":{"solarman_tcp":{
					"status":"timeout",
					"error":"read failed",
					"raw_registers":[500],
					"value":500,
					"definition_snapshot":self.custom_snapshot(definition),
				}},
			}
			with self.assertRaisesRegex(ValueError,"supported scan"):
				save_custom_sensors(str(path),[entry])

		custom_script=(ROOT/"packages/deye_inverter_core/custom_panel.js").read_text(encoding="utf-8")
		self.assertIn('[transport]:{...previousScan,status:"timeout",error:error.message}',custom_script)
		self.assertIn('const testedDefinition=customFrozenCopy(entry.definition)',custom_script)
		self.assertIn('definition_snapshot:definitionSnapshot',custom_script)
		self.assertNotIn('transport !== "solarman_tcp"',custom_script)

	def test_custom_sensor_pending_test_keeps_snapshot_of_submitted_definition(self) -> None:
		custom_script=(ROOT/"packages/deye_inverter_core/custom_panel.js").read_text(encoding="utf-8")
		bootstrap=r'''
const elements=new Map();
const element=id=>{
	if (!elements.has(id)) elements.set(id,{addEventListener(){},style:{},textContent:"",hidden:false,innerHTML:"",value:"",focus(){}});
	return elements.get(id);
};
let resolveFetch;
globalThis.document={
	baseURI:"http://example.test/",
	getElementById:element,
	querySelector(){ return null; },
	querySelectorAll(){ return []; },
	addEventListener(){},
};
globalThis.CSS={escape:value=>value};
globalThis.window={confirm:()=>true};
globalThis.fetch=()=>new Promise(resolve=>{ resolveFetch=resolve; });
'''
		harness=r'''

customSensors=[{
	key:"custom_voltage",
	monitor:true,
	definition:{
		...customDefaultDefinition("custom_voltage"),
		registers:[10],
		transport:"solarman_tcp",
	},
	last_scan:{},
}];

const pending=testCustomSensor("custom_voltage");
customSensors[0].definition.registers=[11];
resolveFetch({ok:true,json:async()=>({value:500,raw_registers:[500],raw_hex:["0x01F4"]})});
pending.then(()=>process.stdout.write(JSON.stringify(customSensors[0]))).catch(error=>{console.error(error);process.exitCode=1;});
'''
		with tempfile.TemporaryDirectory() as directory:
			script_path=Path(directory)/"custom-race.cjs"
			script_path.write_text(bootstrap+"\n"+custom_script+"\n"+harness,encoding="utf-8")
			result=subprocess.run(["node",str(script_path)],capture_output=True,text=True,check=False)
			self.assertEqual(result.returncode,0,result.stdout+result.stderr)
			entry=json.loads(result.stdout)

		self.assertEqual(entry["definition"]["registers"],[11])
		self.assertEqual(entry["last_scan"]["solarman_tcp"]["definition_snapshot"]["registers"],[10])
		with tempfile.TemporaryDirectory() as directory,self.assertRaisesRegex(ValueError,"current read definition"):
			save_custom_sensors(str(Path(directory)/"custom.yaml"),[entry])

	def test_legacy_custom_sensor_without_scan_survives_unchanged_but_transport_change_requires_scan(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			path=Path(directory)/"custom.yaml"
			legacy={
				"version":1,
				"sensors":[{
					"key":"custom_voltage",
					"monitor":True,
					"definition":{"key":"custom_voltage","registers":[10],"type":"uint16"},
				}],
			}
			path.write_text(yaml.safe_dump(legacy),encoding="utf-8")
			loaded=load_custom_sensors(str(path))["sensors"][0]
			unchanged=save_custom_sensors(str(path),[loaded])["sensors"][0]
			self.assertTrue(unchanged["monitor"])
			self.assertEqual(unchanged["definition"]["transport"],"solarman_tcp")
			changed={**unchanged,"definition":{**unchanged["definition"],"transport":"modbus_rtu"}}
			with self.assertRaisesRegex(ValueError,"supported scan"):
				save_custom_sensors(str(path),[changed])
			changed["last_scan"]={"modbus_rtu":{
				"status":"supported",
				"raw_registers":[501],
				"value":501,
				"definition_snapshot":self.custom_snapshot(changed["definition"]),
			}}
			migrated=save_custom_sensors(str(path),[changed])["sensors"][0]
			self.assertEqual(migrated["definition"]["transport"],"modbus_rtu")
			self.assertEqual(migrated["last_scan"]["value"],501)

	def test_legacy_custom_sensor_requires_scan_when_enabling_or_changing_read_definition(self) -> None:
		legacy_definition={"key":"custom_voltage","registers":[10],"type":"uint16"}
		with tempfile.TemporaryDirectory() as directory:
			path=Path(directory)/"custom.yaml"
			path.write_text(yaml.safe_dump({
				"version":1,
				"sensors":[{"key":"custom_voltage","monitor":False,"definition":legacy_definition}],
			}),encoding="utf-8")
			entry=load_custom_sensors(str(path))["sensors"][0]
			entry["monitor"]=True
			with self.assertRaisesRegex(ValueError,"supported scan"):
				save_custom_sensors(str(path),[entry])

		changes=(
			{"registers":[11]},
			{"type":"int16"},
			{"multiplier":2},
			{"offset":1},
			{"word_order":"low_high"},
			{"byte_order":"low_high"},
			{"registers":[],"type":"auto","formula":"return RAW(R10)"},
		)
		for change in changes:
			with self.subTest(change=change),tempfile.TemporaryDirectory() as directory:
				path=Path(directory)/"custom.yaml"
				path.write_text(yaml.safe_dump({
					"version":1,
					"sensors":[{"key":"custom_voltage","monitor":True,"definition":legacy_definition}],
				}),encoding="utf-8")
				entry=load_custom_sensors(str(path))["sensors"][0]
				entry["definition"].update(change)
				with self.assertRaisesRegex(ValueError,"supported scan"):
					save_custom_sensors(str(path),[entry])

	def test_legacy_custom_sensor_allows_presentation_and_polling_edits_without_scan(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			path=Path(directory)/"custom.yaml"
			path.write_text(yaml.safe_dump({
				"version":1,
				"sensors":[{
					"key":"custom_voltage",
					"monitor":True,
					"definition":{"key":"custom_voltage","name":"Old","registers":[10],"type":"uint16"},
				}],
			}),encoding="utf-8")
			entry=load_custom_sensors(str(path))["sensors"][0]
			entry["definition"].update(name="New",read_every=30,report_every=120,icon="mdi:flash")

			saved=save_custom_sensors(str(path),[entry])["sensors"][0]

			self.assertEqual(saved["definition"]["name"],"New")
			self.assertEqual(saved["definition"]["read_every"],30)
			self.assertTrue(saved["monitor"])

	def test_custom_panel_offers_register_read_test_and_controls_panel_has_no_test_button(self) -> None:
		custom_script=(ROOT/"packages/deye_inverter_core/custom_panel.js").read_text(encoding="utf-8")
		control_script=(ROOT/"packages/deye_inverter_core/control_panel.js").read_text(encoding="utf-8")

		self.assertGreaterEqual(custom_script.count('data-custom-test="${customEsc(entry.key)}"'),2)
		self.assertIn('[transport]:{...result,status:"supported",definition_snapshot:definitionSnapshot}',custom_script)
		self.assertNotIn("data-control-test",control_script)

	def test_panel_uses_one_shared_dictionary_and_renders_both_transport_results(self) -> None:
		panel_script=(ROOT/"packages/deye_inverter_core/panel.js").read_text(encoding="utf-8")
		control_script=(ROOT/"packages/deye_inverter_core/control_panel.js").read_text(encoding="utf-8")
		custom_script=(ROOT/"packages/deye_inverter_core/custom_panel.js").read_text(encoding="utf-8")
		web_source=(ROOT/"packages/deye_inverter_core/web.py").read_text(encoding="utf-8")

		self.assertEqual(sum(source.count("function t(") for source in (panel_script,control_script,custom_script,web_source)),1)
		self.assertIn("window.t=t",panel_script)
		self.assertIn("transportResultCards(entry)",web_source)
		self.assertIn("transportResultCards(entry)",control_script)
		self.assertIn("latency_ms",panel_script)
		self.assertIn("supported.length === 1",panel_script)
		self.assertIn("supported.length === 2",panel_script)
		self.assertIn("disabled",panel_script)
		self.assertIn('data-i18n="tabs.sensors">Sensory',web_source)
		self.assertIn('data-i18n="tabs.controls">Sterowanie',web_source)
		self.assertIn('data-i18n="tabs.custom">Własne sensory',web_source)
		self.assertNotIn("data-control-test",control_script)
		self.assertIn('transports:["solarman_tcp","modbus_rtu"]',custom_script)
		self.assertIn("testTransportSelection",custom_script)

	def test_panel_transport_selector_hides_single_choice_and_requires_dual_choice(self) -> None:
		panel_script=(ROOT/"packages/deye_inverter_core/panel.js").read_text(encoding="utf-8")
		bootstrap=r'''
globalThis.window=globalThis;
console.info=()=>{};
window.location={href:"http://example.test/"};
window.addEventListener=()=>{};
globalThis.navigator={language:"en-US"};
globalThis.document={
	baseURI:"http://example.test/",
	title:"",
	documentElement:{dataset:{language:"en"},lang:""},
	querySelectorAll(){ return []; },
	getElementById(){ return null; },
};
globalThis.statusBadge=status=>`<span>${status}</span>`;
globalThis.fetch=async()=>({ok:true,json:async()=>({language:"en",translations:{
	"transport.title":"Transport","transport.select":"Select transport",
	"transport.solarman_tcp":"SolarMan TCP","transport.modbus_rtu":"Modbus RTU (RS485)",
	"status.supported":"supported","status.timeout":"timeout","status.unavailable":"unavailable",
	"result.value":"Value","result.raw":"RAW","result.latency":"Latency","result.error":"Error"
}})});
'''
		harness=r'''
window.i18nReady.then(()=>{
	const single={key:"single",definition:{transport:"solarman_tcp",transports:["solarman_tcp","modbus_rtu"],unit:"V"},last_scan:{solarman_tcp:{status:"timeout"},modbus_rtu:{status:"supported",value:51.2,latency_ms:4}}};
	const dual={key:"dual",definition:{transport:"modbus_rtu",transports:["solarman_tcp","modbus_rtu"],unit:"V"},last_scan:{solarman_tcp:{status:"supported",value:51.1,raw_hex:["0x01FF"],latency_ms:12},modbus_rtu:{status:"supported",value:51.2,latency_ms:4}}};
	process.stdout.write(JSON.stringify({single:window.transportSelector(single),singleTransport:single.definition.transport,dual:window.transportSelector(dual),cards:window.transportResultCards(dual)}));
}).catch(error=>{ console.error(error); process.exitCode=1; });
'''
		with tempfile.TemporaryDirectory() as directory:
			path=Path(directory)/"selector.cjs"
			path.write_text(bootstrap+"\n"+panel_script+"\n"+harness,encoding="utf-8")
			result=subprocess.run(["node",str(path)],capture_output=True,text=True,check=False)
			self.assertEqual(result.returncode,0,result.stdout+result.stderr)
			payload=json.loads(result.stdout)
		self.assertIn('type="hidden"',payload["single"])
		self.assertEqual(payload["singleTransport"],"modbus_rtu")
		self.assertNotIn("<select",payload["dual"])
		self.assertIn('class="select-control"',payload["dual"])
		self.assertIn('type="hidden"',payload["dual"])
		self.assertIn('data-transport="dual"',payload["dual"])
		self.assertIn("Modbus RTU (RS485)",payload["dual"])
		self.assertIn("SolarMan TCP",payload["cards"])
		self.assertIn("Modbus RTU (RS485)",payload["cards"])
		self.assertIn("12 ms",payload["cards"])
		self.assertIn("0x01FF",payload["cards"])

	def test_panel_hides_offline_rs485_choice_but_keeps_supported_history(self) -> None:
		panel_script=(ROOT/"packages/deye_inverter_core/panel.js").read_text(encoding="utf-8")
		bootstrap=r'''
globalThis.window=globalThis;
console.info=()=>{};
window.location={href:"http://example.test/"};
window.addEventListener=()=>{};
globalThis.navigator={language:"en-US"};
const runtimeTarget={innerHTML:""};
globalThis.document={
	baseURI:"http://example.test/",
	title:"",
	documentElement:{dataset:{language:"en"},lang:""},
	querySelectorAll(){ return []; },
	getElementById(id){ return id === "transport-status-list" ? runtimeTarget : null; },
};
globalThis.statusBadge=status=>`<span>${status}</span>`;
globalThis.fetch=async()=>({ok:true,json:async()=>({language:"en",translations:{
	"transport.title":"Transport","transport.select":"Select transport",
	"transport.solarman_tcp":"SolarMan TCP","transport.modbus_rtu":"Modbus RTU (RS485)",
	"status.supported":"supported","status.offline":"offline","status.unavailable":"unavailable",
	"runtime.online":"online","runtime.offline":"offline","runtime.latency":"Latency {value}",
	"runtime.errors":"Errors {value}","runtime.reconnect":"Reconnect {value}",
	"result.value":"Value","result.raw":"RAW","result.latency":"Latency","result.error":"Error"
}})});
'''
		harness=r'''
window.i18nReady.then(()=>{
	const firstChanged=window.renderTransportRuntime({transports:[
		{id:"solarman_tcp",online:true,latency_ms:10,error_count:0},
		{id:"modbus_rtu",online:false,latency_ms:0,error_count:1,last_error:"disconnected"},
	]});
	const unchanged=window.renderTransportRuntime({transports:[
		{id:"solarman_tcp",online:true,latency_ms:12,error_count:0},
		{id:"modbus_rtu",online:false,latency_ms:0,error_count:2,last_error:"still disconnected"},
	]});
	const entry={key:"run_state",definition:{transport:"modbus_rtu",transports:["solarman_tcp","modbus_rtu"]},last_scan:{
		solarman_tcp:{status:"supported",value:"Normal"},
		modbus_rtu:{status:"supported",value:"Normal"},
	}};
	process.stdout.write(JSON.stringify({selector:window.transportSelector(entry),cards:window.transportResultCards(entry),selected:entry.definition.transport,online:window.onlineTransportIds,firstChanged,unchanged}));
}).catch(error=>{ console.error(error); process.exitCode=1; });
'''
		with tempfile.TemporaryDirectory() as directory:
			path=Path(directory)/"offline-selector.cjs"
			path.write_text(bootstrap+"\n"+panel_script+"\n"+harness,encoding="utf-8")
			result=subprocess.run(["node",str(path)],capture_output=True,text=True,check=False)
			self.assertEqual(result.returncode,0,result.stdout+result.stderr)
			payload=json.loads(result.stdout)

		self.assertIn('type="hidden"',payload["selector"])
		self.assertNotIn("<select",payload["selector"])
		self.assertEqual(payload["selected"],"solarman_tcp")
		self.assertEqual(payload["online"],["solarman_tcp"])
		self.assertTrue(payload["firstChanged"])
		self.assertFalse(payload["unchanged"])
		self.assertIn("supported",payload["cards"])
		self.assertIn("offline",payload["cards"])

	def test_custom_panel_exposes_status_decoding_configuration(self) -> None:
		custom_script=(ROOT/"packages/deye_inverter_core/custom_panel.js").read_text(encoding="utf-8")

		self.assertIn('"enum","bitmask"',custom_script)
		self.assertIn("parseStatusOptions",custom_script)
		self.assertIn('customTextarea(entry.key,"options"',custom_script)
		self.assertIn("window.onlineTransportIds",custom_script)

	def test_ingress_dictionaries_are_complete_polish_and_english_variants(self) -> None:
		translations={}
		for language in ("pl","en"):
			path=ROOT/"packages/deye_inverter_core/i18n"/f"{language}.json"
			translations[language]=json.loads(path.read_text(encoding="utf-8"))
			self.assertGreaterEqual(len(translations[language]),80)
			self.assertTrue(all(isinstance(key,str) and isinstance(value,str) and value for key,value in translations[language].items()))
		self.assertEqual(set(translations["pl"]),set(translations["en"]))
		self.assertEqual(translations["pl"]["tabs.sensors"],"Sensory")
		self.assertEqual(translations["pl"]["tabs.controls"],"Sterowanie")
		self.assertEqual(translations["pl"]["tabs.custom"],"Własne sensory")
		self.assertEqual(translations["en"]["tabs.sensors"],"Sensors")
		self.assertEqual(translations["en"]["tabs.controls"],"Controls")
		self.assertEqual(translations["en"]["tabs.custom"],"Custom sensors")

	def test_home_assistant_translations_cover_the_current_schema(self) -> None:
		config=yaml.safe_load((ROOT/"deye-solarman-diagnostics/config.yaml").read_text(encoding="utf-8"))
		self.assertEqual(config["panel_title"],"SolarMan Diagnostics")
		for language in ("pl","en"):
			translated=yaml.safe_load((ROOT/"deye-solarman-diagnostics/translations"/f"{language}.yaml").read_text(encoding="utf-8"))["configuration"]
			self.assertNotIn("logger",translated)
			self.assertNotIn("polling",translated)
			def assert_group(schema,group,path):
				self.assertIn("name",group,path)
				self.assertIn("description",group,path)
				fields=group.get("fields",{})
				for key,value in schema.items():
					self.assertIn(key,fields,f"{path}.{key}")
					self.assertIn("name",fields[key],f"{path}.{key}")
					self.assertIn("description",fields[key],f"{path}.{key}")
					if isinstance(value,dict):
						assert_group(value,fields[key],f"{path}.{key}")
			for section,schema in config["schema"].items():
				self.assertIn(section,translated,section)
				if isinstance(schema,dict):
					assert_group(schema,translated[section],section)
				else:
					self.assertIn("name",translated[section],section)
					self.assertIn("description",translated[section],section)

	def test_exact_modbus_exception_codes_classify_only_illegal_requests_as_unsupported(self) -> None:
		for code in (1,2):
			self.assertEqual(_read_error_status(Exception(f"ExceptionResponse(exception_code={code})")),"unsupported")
		for code in (6,10,11):
			self.assertEqual(_read_error_status(Exception(f"ExceptionResponse(exception_code={code})")),"timeout")
		self.assertEqual(_read_error_status(Exception("ExceptionResponse without a code")),"timeout")
		self.assertEqual(_read_error_status(Exception("Illegal data address")),"unsupported")

	def test_reset_sensor_alias_matches_catalog_default_transport(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			path=Path(directory)/"detected.yaml"
			path.write_text(yaml.safe_dump({
				"version":1,
				"available_sensors":[{
					"key":"voltage",
					"monitor":True,
					"definition":{"key":"voltage","registers":[10],"type":"uint16","transport":"modbus_rtu","transports":["solarman_tcp","modbus_rtu"]},
					"last_scan":{
						"solarman_tcp":{"status":"supported","value":500},
						"modbus_rtu":{"status":"supported","value":501},
					},
				}],
			}),encoding="utf-8")

			entry=reset_detected_sensors(str(path),[self.candidate()])["available_sensors"][0]

			self.assertEqual(entry["definition"]["transport"],"solarman_tcp")
			self.assertEqual(entry["last_scan"]["value"],500)

	def test_control_catalog_rejects_invalid_transport_lists(self) -> None:
		catalog=list(CONTROLS.values())
		control=dict(catalog[0])
		try:
			for transports in ([],["solarman_tcp","solarman_tcp"],["unknown"]):
				with self.subTest(transports=transports),self.assertRaises(ValueError):
					set_controls([{**control,"transports":transports}])
		finally:
			set_controls(catalog)

	def test_control_scan_preserves_success_before_connection_closes_and_marks_slot_offline(self) -> None:
		catalog=list(CONTROLS.values())
		first=dict(CONTROLS["control_grid_charge_battery_current"])
		second=dict(CONTROLS["control_load_limit"])
		set_controls([first,second])
		try:
			with tempfile.TemporaryDirectory() as directory:
				transport=SequentialScanTransport("solarman_tcp",[],{128:37})
				transport.failures[142]=TransportConnectionClosedError("socket closed")
				manager=self.manager(transport,None)
				service=ControlService(
					str(Path(directory)/"controls.json"),
					None,
					threading.Lock(),
					0,
					transport_manager=manager,
				)

				service._scan(lambda:None)

				by_key={entry["key"]:entry for entry in service.load()["available_sensors"]}
				self.assertEqual(by_key[first["key"]]["last_scan"]["solarman_tcp"]["status"],"supported")
				self.assertEqual(by_key[second["key"]]["last_scan"]["solarman_tcp"]["status"],"unavailable")
				self.assertFalse(manager.get("solarman_tcp").online)
		finally:
			set_controls(catalog)

	def test_control_catalog_removal_reselects_supported_allowed_transport(self) -> None:
		catalog=list(CONTROLS.values())
		control=dict(CONTROLS["control_grid_charge_battery_current"])
		try:
			with tempfile.TemporaryDirectory() as directory:
				service=ControlService(str(Path(directory)/"controls.json"),None,threading.Lock(),0)
				previous=service.entry(control["key"])
				previous["definition"]["transport"]="modbus_rtu"
				previous["last_scan"]={
					"solarman_tcp":{"status":"supported","write_allowed":True},
					"modbus_rtu":{"status":"supported","write_allowed":True},
				}
				service.store({"available_sensors":[previous],"published":[]})
				set_controls([{**control,"transports":["solarman_tcp"]}])

				loaded=service.load()["available_sensors"][0]

				self.assertEqual(loaded["definition"]["transport"],"solarman_tcp")
		finally:
			set_controls(catalog)

	def test_control_transport_change_requires_supported_scan_even_when_not_monitored(self) -> None:
		catalog=list(CONTROLS.values())
		control=dict(CONTROLS["control_grid_charge_battery_current"])
		set_controls([control])
		try:
			with tempfile.TemporaryDirectory() as directory:
				service=ControlService(str(Path(directory)/"controls.json"),None,threading.Lock(),0)
				entry=service.entry(control["key"])
				entry["last_scan"]={
					"solarman_tcp":{"status":"supported","write_allowed":True},
					"modbus_rtu":{"status":"timeout"},
				}
				service.store({"available_sensors":[entry],"published":[]})

				with self.assertRaisesRegex(ValueError,"poprawny odczyt"):
					service.update([{
						"key":control["key"],
						"monitor":False,
						"definition":{"transport":"modbus_rtu"},
					}])
		finally:
			set_controls(catalog)

	def test_control_rescan_failure_preserves_legacy_raw_values_and_marks_missing_rs485(self) -> None:
		catalog=list(CONTROLS.values())
		control=dict(CONTROLS["control_grid_charge_battery_current"])
		set_controls([control])
		try:
			with tempfile.TemporaryDirectory() as directory:
				transport=SequentialScanTransport("solarman_tcp",[])
				transport.failures[128]=TimeoutError("no reply")
				service=ControlService(
					str(Path(directory)/"controls.json"),
					None,
					threading.Lock(),
					0,
					transport_factory=lambda logger:transport,
				)
				entry=service.entry(control["key"])
				entry["last_scan"]={"status":"supported","value":37,"raw_registers":[37],"raw_hex":["0x0025"],"write_allowed":True}
				service.store({"available_sensors":[entry],"published":[]})

				service._scan(lambda:None)

				loaded=service.load()["available_sensors"][0]
				self.assertEqual(loaded["last_scan"]["solarman_tcp"]["status"],"timeout")
				self.assertEqual(loaded["last_scan"]["solarman_tcp"]["value"],37)
				self.assertEqual(loaded["last_scan"]["solarman_tcp"]["raw_hex"],["0x0025"])
				self.assertEqual(loaded["last_scan"]["modbus_rtu"]["status"],"unavailable")
		finally:
			set_controls(catalog)

	def test_control_unavailable_rescan_preserves_nested_transport_history(self) -> None:
		catalog=list(CONTROLS.values())
		control=dict(CONTROLS["control_grid_charge_battery_current"])
		set_controls([control])
		try:
			with tempfile.TemporaryDirectory() as directory:
				service=ControlService(
					str(Path(directory)/"controls.json"),
					None,
					threading.Lock(),
					0,
					transport_manager=self.manager(SequentialScanTransport("solarman_tcp",[],{128:37}),None),
				)
				entry=service.entry(control["key"])
				entry["last_scan"]={
					"solarman_tcp":{"status":"supported","value":36,"raw_registers":[36],"raw_hex":["0x0024"]},
					"modbus_rtu":{"status":"supported","value":38,"raw_registers":[38],"raw_hex":["0x0026"]},
				}
				service.store({"available_sensors":[entry],"published":[]})

				service._scan(lambda:None)

				branch=service.load()["available_sensors"][0]["last_scan"]["modbus_rtu"]
				self.assertEqual(branch["status"],"unavailable")
				self.assertEqual(branch["value"],38)
				self.assertEqual(branch["raw_hex"],["0x0026"])
		finally:
			set_controls(catalog)

	def test_control_all_protocol_failures_are_reported_without_false_slot_success(self) -> None:
		catalog=list(CONTROLS.values())
		control=dict(CONTROLS["control_grid_charge_battery_current"])
		set_controls([control])
		try:
			with tempfile.TemporaryDirectory() as directory:
				transport=SequentialScanTransport("solarman_tcp",[])
				transport.failures[128]=TransportProtocolError("CRC mismatch")
				manager=self.manager(transport,None)
				service=ControlService(
					str(Path(directory)/"controls.json"),
					None,
					threading.Lock(),
					0,
					transport_manager=manager,
				)

				service._scan(lambda:None)

				self.assertEqual(service.load()["available_sensors"][0]["last_scan"]["solarman_tcp"]["status"],"timeout")
				slot=manager.get("solarman_tcp")
				self.assertEqual(slot.error_count,1)
				self.assertEqual(slot.last_error,"All control scan reads failed")
				self.assertTrue(slot.online)
		finally:
			set_controls(catalog)

	def test_control_scan_without_manager_respects_each_catalog_transport_list(self) -> None:
		catalog=list(CONTROLS.values())
		rs485_only={**CONTROLS["control_load_limit"],"transports":["modbus_rtu"]}
		solarman_only={**CONTROLS["control_grid_charge_battery_current"],"transports":["solarman_tcp"]}
		set_controls([rs485_only,solarman_only])
		try:
			with tempfile.TemporaryDirectory() as directory:
				class RecordingTransport(SequentialScanTransport):
					def __init__(self) -> None:
						super().__init__("solarman_tcp",[],{128:37,142:50})
						self.read_starts=[]

					def read_holding_registers(self, start: int, count: int) -> list[int]:
						self.read_starts.append(start)
						return super().read_holding_registers(start,count)

				transport=RecordingTransport()
				service=ControlService(
					str(Path(directory)/"controls.json"),
					None,
					threading.Lock(),
					0,
					transport_factory=lambda logger:transport,
				)

				service._scan(lambda:None)

				by_key={entry["key"]:entry for entry in service.load()["available_sensors"]}
				self.assertNotIn(142,transport.read_starts)
				self.assertIn(128,transport.read_starts)
				self.assertEqual(by_key[rs485_only["key"]]["last_scan"]["solarman_tcp"]["status"],"unsupported")
				self.assertEqual(by_key[rs485_only["key"]]["last_scan"]["modbus_rtu"]["status"],"unavailable")
				self.assertEqual(by_key[solarman_only["key"]]["last_scan"]["solarman_tcp"]["status"],"supported")
				self.assertEqual(by_key[solarman_only["key"]]["last_scan"]["modbus_rtu"]["status"],"unsupported")
		finally:
			set_controls(catalog)

	def test_control_reset_alias_matches_catalog_default_transport(self) -> None:
		catalog=list(CONTROLS.values())
		control=dict(CONTROLS["control_grid_charge_battery_current"])
		set_controls([control])
		try:
			with tempfile.TemporaryDirectory() as directory:
				service=ControlService(str(Path(directory)/"controls.json"),None,threading.Lock(),0)
				entry=service.entry(control["key"])
				entry["definition"]["transport"]="modbus_rtu"
				entry["last_scan"]={
					"solarman_tcp":{"status":"supported","value":37,"write_allowed":True},
					"modbus_rtu":{"status":"supported","value":38,"write_allowed":True},
				}
				service.store({"available_sensors":[entry],"published":[]})

				reset=service.reset()["available_sensors"][0]

				self.assertEqual(reset["definition"]["transport"],"solarman_tcp")
				self.assertEqual(reset["last_scan"]["value"],37)
		finally:
			set_controls(catalog)


if __name__ == "__main__":
	unittest.main()
